#!/usr/bin/env bash
# =============================================================================
# NAStool 一键发布脚本
#
# 功能:
#   1) 自动汇总上一个 tag 至 HEAD 的 commit, 清洗去重后生成 CHANGELOG 条目
#   2) 自动修改 version.py, 提交 commit 并打带变更摘要的 annotated tag
#   3) 推送 master 与 tag, 并通过 gh CLI 触发 Docker / Beta / Package 三条流水线
#
# 用法:
#   scripts/release.sh <new_version>            # 例: scripts/release.sh v3.4.2
#   scripts/release.sh <new_version> --dry-run  # 只演练不写入
#   scripts/release.sh <new_version> --no-build # 不触发构建
#   scripts/release.sh <new_version> --no-push  # 不 push 远端 (调试用)
#   scripts/release.sh <new_version> --no-emoji # tag message 不使用 emoji 图标
#   scripts/release.sh <new_version> --tag-limit=20  # tag message 条目上限 (默认 12)
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
NO_BUILD=false
NO_PUSH=false
NO_EMOJI=false
TAG_LIMIT=12
shift || true
for arg in "$@"; do
  case "$arg" in
    --dry-run)  DRY_RUN=true ;;
    --no-build) NO_BUILD=true ;;
    --no-push)  NO_PUSH=true ;;
    --no-emoji) NO_EMOJI=true ;;
    --tag-limit=*) TAG_LIMIT="${arg#*=}" ;;
    *) die "未知参数: $arg" ;;
  esac
done

[[ -z "$NEW_VERSION" ]] && die "用法: $0 <new_version> [--dry-run] [--no-build] [--no-push]"
[[ "$NEW_VERSION" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$ ]] \
  || die "版本号格式应为 vX.Y.Z 或 vX.Y.Z-suffix, 实际: $NEW_VERSION"

# ---------- 路径 ----------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
VERSION_FILE="$REPO_ROOT/version.py"
CHANGELOG="$REPO_ROOT/docs/CHANGELOG.md"
RELEASE_ENV_FILE="$REPO_ROOT/.release"

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
[[ -f "$CHANGELOG"     ]] || die "未找到 $CHANGELOG"

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

[[ "$CUR_VERSION" == "$NEW_VERSION" ]] && die "目标版本与当前版本相同"
git rev-parse "$NEW_VERSION" >/dev/null 2>&1 && die "tag $NEW_VERSION 已存在"

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

buckets = collections.OrderedDict(
    (k, []) for k in ["Breaking", "Added", "Changed", "Fixed", "Removed", "Deprecated", "Security"]
)
seen_norm = set()
all_short_hashes = []

for line in raw.splitlines():
    parts = line.split("\t")
    if len(parts) < 2:
        continue
    h, subject = parts[0], parts[1].strip()
    short = h[:7]
    all_short_hashes.append(short)
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
    buckets[cat].append((norm, short))

# 输出三段:
# 1) MARK_CHANGELOG  : 写到 docs/CHANGELOG.md 的整段
# 2) MARK_TAG        : 写到 git tag annotated message 的精简版 (只保留有内容的类目, 上限 12 条)
# 3) MARK_HIGHLIGHTS : 5 条以内核心修改点 (Breaking > Added > Fixed > Changed)

new_version = os.environ["NEW_VERSION"]
import datetime
today = datetime.date.today().isoformat()

cl_lines = [f"## [{new_version}] - {today}", ""]
cl_lines.append(f"> 自动生成自 {os.environ.get('RANGE_LABEL', 'previous')} 至本次发布的 commit。")
cl_lines.append("")
any_content = False
for cat, items in buckets.items():
    if not items:
        continue
    any_content = True
    cl_lines.append(f"### {cat}")
    for norm, short in items:
        cl_lines.append(f"- {norm} ({short})")
    cl_lines.append("")
if not any_content:
    cl_lines.append("### Changed")
    cl_lines.append("- 内部维护性变更, 详见 git log")
    cl_lines.append("")

print("MARK_CHANGELOG")
print("\n".join(cl_lines))
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
    for norm, short in items:
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
    tag_lines.append(f"… +{remaining} more entries — see docs/CHANGELOG.md")

print("MARK_TAG")
print("\n".join(tag_lines).rstrip())
print("MARK_END")

# highlights (max 5)
priority = ["Breaking", "Added", "Fixed", "Changed", "Removed", "Security", "Deprecated"]
highlights = []
for cat in priority:
    for norm, short in buckets.get(cat, []):
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
  python3 "$TMP_PY" <<<"$RAW_LOG")"

extract() {
  awk -v key="$1" '
    $0 == key { capture=1; next }
    capture && $0 == "MARK_END" { exit }
    capture { print }
  ' <<<"$PARSED"
}

CL_SECTION="$(extract MARK_CHANGELOG)"
TAG_MSG="$(extract MARK_TAG)"
HIGHLIGHTS="$(extract MARK_HIGHLIGHTS)"

[[ -z "$CL_SECTION" ]] && die "Changelog 解析失败"

echo
echo "============== 生成的 CHANGELOG 条目 =============="
echo "$CL_SECTION"
echo "============== 生成的 Tag message ================="
echo "$TAG_MSG"
echo "==================================================="
echo

if $DRY_RUN; then
  warn "--dry-run, 不写入文件 / 不打 tag / 不 push / 不触发构建"
  exit 0
fi

# ---------- 写 CHANGELOG ----------
log "更新 docs/CHANGELOG.md..."
# 在 ## [Unreleased] 节之后插入新版本条目, 同时清空 Unreleased 内容回到模板
python3 - "$CHANGELOG" <<PYEOF
import io, re, sys
path = sys.argv[1]
with io.open(path, "r", encoding="utf-8") as f:
    text = f.read()

new_section = """$CL_SECTION
---

"""

# 1) 把生成内容插到 [Unreleased] 章节之后(下一个 ## 之前)
m = re.search(r"^## \[Unreleased\][\s\S]*?(?=^## )", text, re.M)
if not m:
    # 若不存在 Unreleased 节则插在第一个 ## 前
    m2 = re.search(r"^## ", text, re.M)
    insert_at = m2.start() if m2 else len(text)
    text = text[:insert_at] + new_section + text[insert_at:]
else:
    text = text[:m.end()] + new_section + text[m.end():]

# 2) 重置 Unreleased 内容
unreleased_template = """## [Unreleased]

> 下一版本开发中尚未发布的变更。

### Added
- _（待补充）_

### Changed
- _（待补充）_

### Fixed
- _（待补充）_

---

"""
text = re.sub(r"^## \[Unreleased\][\s\S]*?(?=^## )", unreleased_template, text, count=1, flags=re.M)

# 3) 同步顶部「当前最新版本」字段
text = re.sub(r"(当前最新版本：\*\*)v[^*]+(\*\*)", r"\1$NEW_VERSION\2", text)

with io.open(path, "w", encoding="utf-8") as f:
    f.write(text)
print("CHANGELOG 已更新")
PYEOF

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
git add "$VERSION_FILE" "$CHANGELOG"
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
if $NO_BUILD; then
  warn "--no-build, 跳过构建触发"
  exit 0
fi
if $NO_PUSH; then
  warn "--no-push 时跳过构建触发 (流水线在远端 commit/tag 上跑)"
  exit 0
fi

if ! command -v gh >/dev/null 2>&1; then
  warn "未安装 gh CLI, 请到 GitHub Actions 页面手动触发以下三条流水线:"
  echo "    - .github/workflows/build.yml"
  echo "    - .github/workflows/build-beta.yml"
  echo "    - .github/workflows/build-package.yml"
  exit 0
fi

: "${DOCKER_USERNAME:?需要在 .release 文件中配置 DOCKER_USERNAME (或加 --no-build)}"
: "${DOCKER_PASSWORD:?需要在 .release 文件中配置 DOCKER_PASSWORD (或加 --no-build)}"
: "${RELEASE_GH_TOKEN:?需要在 .release 文件中配置 RELEASE_GH_TOKEN (或加 --no-build)}"

log "通过 gh 触发 build.yml (Docker Hub 主线)..."
gh workflow run build.yml --ref "$CUR_BRANCH" \
  -f docker_username="$DOCKER_USERNAME" \
  -f docker_password="$DOCKER_PASSWORD"

log "通过 gh 触发 build-package.yml (二进制 + Release)..."
gh workflow run build-package.yml --ref "$CUR_BRANCH" \
  -f github_token="$RELEASE_GH_TOKEN"

ok "构建已派发, 在 GitHub Actions 页面查看进度"
echo
echo "    Docker Hub : https://hub.docker.com/r/${DOCKER_USERNAME}/nastools/tags"
echo "    Releases   : https://github.com/$(git config --get remote.origin.url \
                          | sed -E 's#.*github.com[:/](.*)\.git#\1#')/releases"
echo
ok "Release $NEW_VERSION 已完成本地侧动作 ✅"
