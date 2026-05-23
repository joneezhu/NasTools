#!/usr/bin/env bash
# =============================================================================
# NAStool 一键发布脚本
#
# 功能:
#   1) 自动汇总上一个 tag 至 HEAD 的 commit, 清洗去重后生成 CHANGELOG 条目
#   2) 自动修改 version.py, 提交 commit 并打带变更摘要的 annotated tag
#   3) 推送 master 与 tag, 并通过 gh CLI 触发 Docker (build.yml) 与 Package (build-package.yml) 流水线
#
# 用法:
#   scripts/release.sh <new_version>            # 例: scripts/release.sh v3.4.2 (默认不触发构建)
#   scripts/release.sh <new_version> --build    # 推送后立即触发 docker / package 流水线
#   scripts/release.sh <new_version> --dry-run  # 只演练不写入
#   scripts/release.sh <new_version> --no-push  # 不 push 远端 (调试用)
#   scripts/release.sh <new_version> --no-emoji # tag message 不使用 emoji 图标
#   scripts/release.sh <new_version> --tag-limit=20  # tag message 条目上限 (默认 12)
#
# 默认行为:
#   * 默认 *不* 触发 GitHub Actions, 仅生成 changelog / commit / tag / push。
#     CI 触发改为按需手动触发, 避免误触发或在 tag 失败时产生僵尸 run。
#   * 触发构建请加 --build, 此时会通过 gh workflow run 派发 build.yml 与 build-package.yml,
#     且 ref 一律使用新 tag (而不是 master 分支), 这样 build-package.yml 出的 Release 会绑定到 tag。
#
# 凭据来源 (触发构建时需要):
#   项目根目录 .release 文件 (KEY=VALUE 格式, 已 gitignore), 至少包含:
#     DOCKER_USERNAME=...
#     DOCKER_PASSWORD=...
#     RELEASE_GH_TOKEN=...
#   shell 中已设置的同名环境变量优先级更高, 会覆盖 .release 中的值。
#
# 依赖: git, gh (GitHub CLI), python3
# =============================================================================
set -euo pipefail

# ---------- 工具 ----------
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERR]${NC}   $*" >&2; }
die()  { err "$*"; exit 1; }

# ---------- 参数 ----------
NEW_VERSION="${1:-}"
DRY_RUN=false
RUN_BUILD=false        # 默认不触发 CI; 加 --build 才会跑
NO_PUSH=false
NO_EMOJI=false
TAG_LIMIT=12
shift || true
for arg in "$@"; do
  case "$arg" in
    --dry-run)  DRY_RUN=true ;;
    --build)    RUN_BUILD=true ;;
    --no-build) RUN_BUILD=false ;;   # 兼容旧用法 (其实是默认值)
    --no-push)  NO_PUSH=true ;;
    --no-emoji) NO_EMOJI=true ;;
    --tag-limit=*) TAG_LIMIT="${arg#*=}" ;;
    *) die "未知参数: $arg" ;;
  esac
done

[[ -z "$NEW_VERSION" ]] && die "用法: $0 <new_version> [--build] [--dry-run] [--no-push]"
[[ "$NEW_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$ ]] \
  || die "版本号格式应为 vX.Y.Z 或 vX.Y.Z-suffix, 实际: $NEW_VERSION"

# ---------- 路径 ----------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
VERSION_FILE="$REPO_ROOT/version.py"
# 自 v3.4.x 起放弃 docs/CHANGELOG.md 单文件总账, 改为只维护单 tag 文件 docs/changelog/<tag>.md。
# CHANGELOG.md 保留为静态导览 (说明 + 索引), 不再被 release.sh 写入。
CHANGELOG_DIR="$REPO_ROOT/docs/changelog"
RELEASE_ENV_FILE="$REPO_ROOT/.release"

mkdir -p "$CHANGELOG_DIR"

# ---------- 加载 .release 凭据 ----------
# .release 是 KEY=VALUE 形式的环境文件 (已加入 .gitignore, 不会上传)
# 至少需要: DOCKER_USERNAME / DOCKER_PASSWORD / RELEASE_GH_TOKEN
if [[ -f "$RELEASE_ENV_FILE" ]]; then
  log "加载 $RELEASE_ENV_FILE"
  # 安全读取: 只允许 KEY=VALUE 形式的纯赋值, 自动过滤注释和空行
  while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
    line="${raw_line%%#*}"          # 去掉 # 之后的注释
    line="${line#"${line%%[![:space:]]*}"}"  # ltrim
    line="${line%"${line##*[![:space:]]}"}"  # rtrim
    [[ -z "$line" ]] && continue
    if [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      key="${line%%=*}"
      val="${line#*=}"
      # 剥掉首尾成对的引号 (兼容 bash 3.2 的写法)
      if [[ "$val" =~ ^\"(.*)\"$ ]] || [[ "$val" =~ ^\'(.*)\'$ ]]; then
        val="${BASH_REMATCH[1]}"
      fi
      # shell 中已存在且非空的同名变量优先, 不覆盖
      if [[ -z "${!key:-}" ]]; then
        export "$key=$val"
      fi
    else
      warn "$RELEASE_ENV_FILE 忽略非法行: $raw_line"
    fi
  done < "$RELEASE_ENV_FILE"
else
  warn "$RELEASE_ENV_FILE 不存在, 触发构建时将失败 (除非显式 --no-build)"
fi

# ---------- 前置校验 ----------
log "校验工作区..."
[[ -f "$VERSION_FILE"  ]] || die "未找到 $VERSION_FILE"
[[ -d "$CHANGELOG_DIR"  ]] || mkdir -p "$CHANGELOG_DIR"

if ! $DRY_RUN; then
  if ! git diff --quiet || ! git diff --cached --quiet; then
    die "工作区有未提交的修改, 先 stash 或 commit"
  fi
fi

CUR_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
[[ "$CUR_BRANCH" == "master" || "$CUR_BRANCH" == "main" ]] \
  || warn "当前不在 master/main 分支 ($CUR_BRANCH), 仍可继续"

# 拉最新
$DRY_RUN || { log "git fetch --tags"; git fetch --tags --quiet; }

# 取上一个 tag
LAST_TAG="$(git tag --sort=-creatordate | head -n1 || true)"
if [[ -z "$LAST_TAG" ]]; then
  warn "未找到任何已有 tag, 将从首个 commit 起算"
  RANGE_FROM="$(git rev-list --max-parents=0 HEAD | head -n1)"
  RANGE_LABEL="(首次发布)"
else
  RANGE_FROM="$LAST_TAG"
  RANGE_LABEL="$LAST_TAG"
fi

# 解析当前版本号
CUR_VERSION="$(grep -E "^APP_VERSION" "$VERSION_FILE" | sed -E "s/.*'(v[^']+)'.*/\1/")"
log "当前版本: $CUR_VERSION  ->  目标版本: $NEW_VERSION"
log "Changelog 范围: $RANGE_LABEL  ->  HEAD"

# 解析远端仓库 owner/repo, 用于生成 commit / issue 超链接
REMOTE_URL="$(git config --get remote.origin.url 2>/dev/null || true)"
OWNER_REPO="$(echo "$REMOTE_URL" | sed -E 's#.*github.com[:/](.*)\.git$#\1#')"
if [[ -z "$OWNER_REPO" || "$OWNER_REPO" == "$REMOTE_URL" ]]; then
  warn "无法从 origin 解析 GitHub owner/repo, changelog 将不带超链接"
  OWNER_REPO=""
fi

# ---------- 已有 tag / Release 状态判定 ----------
# 三种情况:
#   A) tag 不存在               -> 走完整流程 (生成 changelog / commit / tag / push / 触发构建)
#   B) tag 已存在 + Release 有安装包 -> 直接退出, 无事可做
#   C) tag 已存在 + Release 无安装包 -> 跳过 commit/tag/push, 仅触发 build-package.yml 重新出包
#
# 安装包存在性: 当对应 tag 的 GitHub Release 存在且至少有 1 个 asset 视为已发布。
TAG_EXISTS=false
PACKAGE_EXISTS=false
SKIP_COMMIT_TAG=false
ONLY_REBUILD_PACKAGE=false

# 本地或远端任一存在即视为 tag 已存在
if git rev-parse "$NEW_VERSION" >/dev/null 2>&1; then
  TAG_EXISTS=true
elif git ls-remote --tags --exit-code origin "refs/tags/$NEW_VERSION" >/dev/null 2>&1; then
  TAG_EXISTS=true
fi

if $TAG_EXISTS; then
  log "检测到 tag $NEW_VERSION 已存在, 检查 Release 安装包状态..."
  if command -v gh >/dev/null 2>&1; then
    # 先确认 gh 认证状态, 未认证时直接拒绝判定 (避免把"无权限"误判成"无安装包"导致重复发布)
    if ! gh auth status >/dev/null 2>&1; then
      die "tag $NEW_VERSION 已存在, 但 gh CLI 未登录, 无法判断 Release 是否已有安装包。
      请先执行: gh auth login   (或在 .release 中配置 GH_TOKEN=\$RELEASE_GH_TOKEN)"
    fi
    # 临时关闭 errexit, gh release view 在 Release 不存在时会 exit 1
    set +e
    gh_release_json="$(gh release view "$NEW_VERSION" --json assets,tagName 2>/dev/null)"
    gh_rc=$?
    set -e
    if [[ $gh_rc -eq 0 && -n "$gh_release_json" ]]; then
      asset_count="$(python3 -c "import json,sys; d=json.loads(sys.argv[1]); print(len(d.get('assets', [])))" "$gh_release_json" 2>/dev/null || echo 0)"
      if [[ "$asset_count" -gt 0 ]]; then
        PACKAGE_EXISTS=true
      fi
      log "Release 状态: tag=$NEW_VERSION, assets=$asset_count"
    else
      log "未找到 $NEW_VERSION 的 GitHub Release"
    fi
  else
    die "tag $NEW_VERSION 已存在, 但未安装 gh CLI, 无法判断 Release 是否已有安装包。
      请先安装: brew install gh, 然后 gh auth login"
  fi

  if $PACKAGE_EXISTS; then
    ok "tag $NEW_VERSION 已存在且 Release 已包含安装包 ($asset_count 个), 无需重复发布"
    echo "    Release: https://github.com/$(git config --get remote.origin.url \
                          | sed -E 's#.*github.com[:/](.*)\.git#\1#')/releases/tag/$NEW_VERSION"
    exit 0
  fi

  warn "tag $NEW_VERSION 已存在但 Release 缺少安装包, 将仅重跑 build-package.yml"
  SKIP_COMMIT_TAG=true
  ONLY_REBUILD_PACKAGE=true
else
  [[ "$CUR_VERSION" == "$NEW_VERSION" ]] && die "目标版本与当前版本相同 (且未打 tag), 请先确认 version.py"
fi

# ---------- 仅重跑打包流水线模式 ----------
if $ONLY_REBUILD_PACKAGE; then
  if $DRY_RUN; then
    warn "--dry-run, 仅重跑安装包模式: 不会实际触发 build-package.yml"
    log "(本应触发) gh workflow run build-package.yml --ref $NEW_VERSION"
    exit 0
  fi
  if ! $RUN_BUILD; then
    warn "默认未触发 CI (加 --build 才会派发 build-package.yml)"
    echo "    需要触发请运行: scripts/release.sh $NEW_VERSION --build"
    exit 0
  fi
  : "${RELEASE_GH_TOKEN:?需要在 .release 文件中配置 RELEASE_GH_TOKEN}"

  log "通过 gh 触发 build-package.yml (基于已有 tag $NEW_VERSION 重新出包)..."
  # 用 tag 作为 ref, 流水线里读到的 version.py 就是该 tag 上的版本
  gh workflow run build-package.yml --ref "$NEW_VERSION" \
    -f github_token="$RELEASE_GH_TOKEN"
  ok "build-package.yml 已派发 (ref=$NEW_VERSION)"
  echo
  echo "    Actions  : https://github.com/$(git config --get remote.origin.url \
                          | sed -E 's#.*github.com[:/](.*)\.git#\1#')/actions/workflows/build-package.yml"
  echo "    Releases : https://github.com/$(git config --get remote.origin.url \
                          | sed -E 's#.*github.com[:/](.*)\.git#\1#')/releases"
  echo
  ok "已为已有 tag $NEW_VERSION 重跑安装包流水线 ✅"
  exit 0
fi

# ---------- 收集 / 清洗 commit ----------
log "收集 commit 并清洗..."

RAW_LOG="$(git log "$RANGE_FROM..HEAD" --no-merges --pretty=format:'%H%x09%s%x09%an' || true)"
[[ -z "$RAW_LOG" ]] && die "$RANGE_LABEL..HEAD 之间没有 commit, 没有可发布内容"

# 用 python 做去重 / 分类 / 过滤, 比 awk 可读
TMP_PY="$(mktemp -t release-cl.XXXXXX.py)"
trap 'rm -f "$TMP_PY"' EXIT

cat > "$TMP_PY" <<'PYEOF'
import os, re, sys, collections

raw = sys.stdin.read().strip()
if not raw:
    sys.exit(0)

# 噪声过滤: 只看 subject, 不区分大小写
NOISE_PATTERNS = [
    r"^merge\b", r"^revert\b", r"^wip\b", r"^tmp\b", r"^test\b",
    r"^typo\b", r"^fix typo", r"^update\s+readme", r"^chore:?\s*format",
    r"^chore:?\s*lint", r"^chore:?\s*deps?\s+update",
    r"^bump\s+version", r"^release:?", r"^ci:?\s*", r"^style:?\s*",
    r"^\.{0,3}$", r"^\s*$",
]
NOISE_RE = re.compile("|".join(NOISE_PATTERNS), re.I)

# 分类规则 (Keep a Changelog 类目)
CLASSIFY = [
    ("Breaking", re.compile(r"^(breaking|break)[:!\s]|!:", re.I)),
    ("Security", re.compile(r"^(sec|security)[:\s]|cve-?\d+", re.I)),
    ("Added",    re.compile(r"^(feat|add|new)[:\s\(]", re.I)),
    ("Fixed",    re.compile(r"^(fix|bug|hotfix|patch)[:\s\(]", re.I)),
    ("Removed",  re.compile(r"^(remove|delete|drop|del)[:\s\(]", re.I)),
    ("Deprecated", re.compile(r"^(deprecat)[:\s\(]", re.I)),
    ("Changed",  re.compile(r"^(refactor|perf|chore|docs?|style|change|update|improve|ref)[:\s\(]", re.I)),
]

def classify(subject):
    for cat, rx in CLASSIFY:
        if rx.search(subject):
            return cat
    return "Changed"

def normalize(subject):
    # 去前缀类型 (feat:/fix(scope):/...) 让条目更干净
    s = re.sub(r"^[a-zA-Z]+(\([^)]+\))?!?:\s*", "", subject).strip()
    # 首字母大写
    if s:
        s = s[0].upper() + s[1:]
    return s

OWNER_REPO = os.environ.get("OWNER_REPO", "").strip()

def commit_link(short, full):
    """commit 短哈希 -> markdown 链接 (无 OWNER_REPO 时退化为纯短哈希)"""
    if not OWNER_REPO:
        return short
    return f"[`{short}`](https://github.com/{OWNER_REPO}/commit/{full})"

def linkify_issues(text):
    """正文里 #123 / GH-123 -> markdown 链接 (无 OWNER_REPO 时不动)"""
    if not OWNER_REPO:
        return text
    def repl(m):
        num = m.group(1)
        return f"[#{num}](https://github.com/{OWNER_REPO}/issues/{num})"
    # 仅匹配独立 token 的 #123 (前面非字母数字), 避免 markdown 标题/代码里的误伤
    return re.sub(r"(?:(?<=^)|(?<=[\s(\[,;:]))(?:#|GH-)(\d+)\b", repl, text)

buckets = collections.OrderedDict(
    (k, []) for k in ["Breaking", "Added", "Changed", "Fixed", "Removed", "Deprecated", "Security"]
)
seen_norm = set()
all_short_hashes = []
all_full_hashes = {}   # short -> full

for line in raw.splitlines():
    parts = line.split("\t")
    if len(parts) < 2:
        continue
    h, subject = parts[0], parts[1].strip()
    short = h[:7]
    all_short_hashes.append(short)
    all_full_hashes[short] = h
    if NOISE_RE.search(subject):
        continue
    norm = normalize(subject)
    if not norm:
        continue
    key = norm.lower()
    if key in seen_norm:
        continue
    seen_norm.add(key)
    cat = classify(subject)
    buckets[cat].append((norm, short, h))

# 输出两段:
# 1) MARK_CHANGELOG_FILE : 写到 docs/changelog/<tag>.md 的整段 (供 GitHub Release body)
# 2) MARK_TAG            : 写到 git tag annotated message 的精简版 (只保留有内容的类目, 上限 12 条)
# 3) MARK_HIGHLIGHTS     : 5 条以内核心修改点 (Breaking > Added > Fixed > Changed)
#
# 注: 自 v3.4.x 起放弃 docs/CHANGELOG.md 总账, 不再生成 MARK_CHANGELOG 块。

new_version = os.environ["NEW_VERSION"]
import datetime
today = datetime.date.today().isoformat()

# 单 tag 文件 (docs/changelog/<tag>.md)
# 这是唯一的 changelog 落地形态, 同时作为 GitHub Release body
file_lines = [
    f"# Release {new_version}",
    "",
    f"- **Date**: {today}",
    f"- **Range**: {os.environ.get('RANGE_LABEL', 'previous')} → {new_version}",
    f"- **Commits**: {sum(len(v) for v in buckets.values())} kept / {len(all_short_hashes)} total",
]
# Compare 链接 (上一个 tag 不存在时省略)
prev_label = os.environ.get("RANGE_LABEL", "")
if OWNER_REPO and prev_label and prev_label.startswith("v"):
    file_lines.append(
        f"- **Compare**: [{prev_label}...{new_version}]"
        f"(https://github.com/{OWNER_REPO}/compare/{prev_label}...{new_version})"
    )
file_lines += [
    "",
    "---",
    "",
]
any_in_file = False
for cat, items in buckets.items():
    if not items:
        continue
    any_in_file = True
    file_lines.append(f"## {cat}")
    file_lines.append("")
    for norm, short, full in items:
        file_lines.append(f"- {linkify_issues(norm)} ({commit_link(short, full)})")
    file_lines.append("")
if not any_in_file:
    file_lines.append("## Changed")
    file_lines.append("")
    file_lines.append("- 内部维护性变更, 详见 git log")
    file_lines.append("")

print("MARK_CHANGELOG_FILE")
print("\n".join(file_lines).rstrip())
print("MARK_END")

# tag message
# 风格: 顶部为标题区(版本/范围/统计), 中间是类目分组, 底部是溢出提示
USE_EMOJI = os.environ.get("USE_EMOJI", "1") == "1"
TAG_LIMIT = int(os.environ.get("TAG_LIMIT", "12"))

CAT_ICONS = {
    "Breaking":   ("⚠️ ", "[!] "),
    "Added":      ("✨ ", "[+] "),
    "Changed":    ("♻️ ", "[~] "),
    "Fixed":      ("🐛 ", "[*] "),
    "Removed":    ("🗑️ ", "[-] "),
    "Deprecated": ("⏳ ", "[d] "),
    "Security":   ("🔒 ", "[s] "),
}

def cat_label(cat):
    icon = CAT_ICONS[cat][0 if USE_EMOJI else 1]
    return f"{icon}{cat}"

prev_label = os.environ.get("RANGE_LABEL", "previous")
total_kept = sum(len(v) for v in buckets.values())
total_raw  = len(all_short_hashes)
non_empty_cats = [c for c, v in buckets.items() if v]

# 顶部标题区
sep_line = "─" * 48
tag_lines = [
    f"Release {new_version}",
    sep_line,
    f"Range  : {prev_label} → {new_version}",
    f"Date   : {today}",
    f"Commits: {total_kept} kept / {total_raw} total" + (
        f"  ·  Categories: {len(non_empty_cats)}" if non_empty_cats else ""
    ),
    sep_line,
    "",
]

total_in_tag = 0
overflow = False
for cat, items in buckets.items():
    if not items:
        continue
    tag_lines.append(f"{cat_label(cat)}  ({len(items)})")
    for norm, short, full in items:
        if total_in_tag >= TAG_LIMIT:
            overflow = True
            break
        tag_lines.append(f"  • {norm}  ({short})")
        total_in_tag += 1
    tag_lines.append("")
    if overflow:
        break

if overflow:
    remaining = total_kept - total_in_tag
    tag_lines.append(sep_line)
    tag_lines.append(f"… +{remaining} more entries — see docs/changelog/{new_version}.md")

print("MARK_TAG")
print("\n".join(tag_lines).rstrip())
print("MARK_END")

# highlights (max 5)
priority = ["Breaking", "Added", "Fixed", "Changed", "Removed", "Security", "Deprecated"]
highlights = []
for cat in priority:
    for norm, short, full in buckets.get(cat, []):
        if len(highlights) >= 5:
            break
        highlights.append(f"[{cat}] {norm}")
    if len(highlights) >= 5:
        break

print("MARK_HIGHLIGHTS")
print("\n".join(highlights))
print("MARK_END")
PYEOF

if $NO_EMOJI; then USE_EMOJI_VAL=0; else USE_EMOJI_VAL=1; fi
PARSED="$(NEW_VERSION="$NEW_VERSION" RANGE_LABEL="$RANGE_LABEL" \
  USE_EMOJI="$USE_EMOJI_VAL" TAG_LIMIT="$TAG_LIMIT" \
  OWNER_REPO="$OWNER_REPO" \
  python3 "$TMP_PY" <<<"$RAW_LOG")"

extract() {
  awk -v key="$1" '
    $0 == key { capture=1; next }
    capture && $0 == "MARK_END" { exit }
    capture { print }
  ' <<<"$PARSED"
}

CL_FILE_BODY="$(extract MARK_CHANGELOG_FILE)"
TAG_MSG="$(extract MARK_TAG)"
HIGHLIGHTS="$(extract MARK_HIGHLIGHTS)"

[[ -z "$CL_FILE_BODY" ]] && die "单 tag changelog 文件解析失败"

echo
echo "============== 生成的 changelog (docs/changelog/${NEW_VERSION}.md) =============="
echo "$CL_FILE_BODY"
echo "============== 生成的 Tag message ================="
echo "$TAG_MSG"
echo "==================================================="
echo

if $DRY_RUN; then
  warn "--dry-run, 不写入文件 / 不打 tag / 不 push / 不触发构建"
  exit 0
fi

# ---------- 写 docs/changelog/<tag>.md (单 tag 单文件, 给 GitHub Release 用) ----------
# 这是 changelog 的唯一落地点。docs/CHANGELOG.md 仅作静态导览, 不再被脚本写入。
TAG_CHANGELOG_FILE="$CHANGELOG_DIR/${NEW_VERSION}.md"
log "写入单 tag changelog: docs/changelog/${NEW_VERSION}.md"
printf '%s\n' "$CL_FILE_BODY" > "$TAG_CHANGELOG_FILE"

# ---------- 写 version.py ----------
log "更新 version.py..."
python3 - "$VERSION_FILE" "$NEW_VERSION" <<'PYEOF'
import io, re, sys
path, ver = sys.argv[1], sys.argv[2]
with io.open(path, "r", encoding="utf-8") as f:
    text = f.read()
new_text = re.sub(r"APP_VERSION\s*=\s*'[^']*'", f"APP_VERSION = '{ver}'", text)
with io.open(path, "w", encoding="utf-8") as f:
    f.write(new_text)
print(f"APP_VERSION -> {ver}")
PYEOF

# ---------- commit & tag ----------
log "提交版本 commit..."
git add "$VERSION_FILE" "$TAG_CHANGELOG_FILE"
git commit -m "release: bump version to $NEW_VERSION

$HIGHLIGHTS"

log "打 annotated tag $NEW_VERSION..."
git tag -a "$NEW_VERSION" -F - <<EOF_TAG
$TAG_MSG
EOF_TAG

ok "已创建 commit 与 tag $NEW_VERSION"

# ---------- push ----------
if $NO_PUSH; then
  warn "--no-push, 不推送远端 (commit/tag 仅在本地)"
else
  log "推送 master 与 tag..."
  git push origin "$CUR_BRANCH"
  git push origin "$NEW_VERSION"
  ok "已推送 $CUR_BRANCH 与 tag $NEW_VERSION"
fi

# ---------- 触发构建 ----------
if ! $RUN_BUILD; then
  warn "默认未触发 CI (本地已生成 commit/tag/changelog 并完成 push)"
  echo
  echo "    需要触发构建请运行 (会基于 tag $NEW_VERSION 派发 workflow):"
  echo "      scripts/release.sh $NEW_VERSION --build"
  echo "    或者直接手动:"
  echo "      gh workflow run build.yml         --ref $NEW_VERSION -f docker_username=... -f docker_password=... -f channel=stable"
  echo "      gh workflow run build-package.yml --ref $NEW_VERSION -f github_token=..."
  echo "    (beta 通道: -f channel=beta; 同时跑稳定+beta: -f channel=both)"
  echo
  ok "Release $NEW_VERSION 本地动作完成 ✅ (CI 未触发)"
  exit 0
fi
if $NO_PUSH; then
  warn "--no-push 时跳过构建触发 (流水线在远端 commit/tag 上跑)"
  exit 0
fi

if ! command -v gh >/dev/null 2>&1; then
  warn "未安装 gh CLI, 请到 GitHub Actions 页面手动触发以下两条流水线 (ref 选 tag $NEW_VERSION):"
  echo "    - .github/workflows/build.yml         (channel=stable / beta / both)"
  echo "    - .github/workflows/build-package.yml"
  exit 0
fi

: "${DOCKER_USERNAME:?需要在 .release 文件中配置 DOCKER_USERNAME (或去掉 --build)}"
: "${DOCKER_PASSWORD:?需要在 .release 文件中配置 DOCKER_PASSWORD (或去掉 --build)}"
: "${RELEASE_GH_TOKEN:?需要在 .release 文件中配置 RELEASE_GH_TOKEN (或去掉 --build)}"

# ref 一律用新 tag, 而非 master 分支:
# 1) build-package.yml 的 softprops/action-gh-release 默认会把 Release 绑到 ref 对应的 tag
# 2) 用分支名时, 如果之后该分支又有新 commit, ref 会漂移; 用 tag 永远精确指向本次发布
log "通过 gh 触发 build.yml (Docker Hub 主线 stable 通道, ref=$NEW_VERSION)..."
# 默认只跑 stable 通道 (Alpine + Debian); 如需 beta 单独手动派发:
#   gh workflow run build.yml --ref <tag> -f channel=beta -f docker_username=... -f docker_password=...
gh workflow run build.yml --ref "$NEW_VERSION" \
  -f docker_username="$DOCKER_USERNAME" \
  -f docker_password="$DOCKER_PASSWORD" \
  -f channel=stable

log "通过 gh 触发 build-package.yml (二进制 + Release, ref=$NEW_VERSION)..."
gh workflow run build-package.yml --ref "$NEW_VERSION" \
  -f github_token="$RELEASE_GH_TOKEN"

ok "构建已派发 (ref=$NEW_VERSION), 在 GitHub Actions 页面查看进度"
echo
echo "    Docker Hub : https://hub.docker.com/r/${DOCKER_USERNAME}/nastools/tags"
echo "    Releases   : https://github.com/$(git config --get remote.origin.url \
                          | sed -E 's#.*github.com[:/](.*)\.git#\1#')/releases"
echo
ok "Release $NEW_VERSION 已完成本地侧动作 ✅"
