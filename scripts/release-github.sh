#!/usr/bin/env bash
# =============================================================================
# NAStool GitHub Release 自动化脚本
#
# 功能:
#   生成"自上一个已发布 Release 至当前 tag"的扁平 changelog 作为 body,
#   调用 gh release create / edit 创建或更新 GitHub Release。
#
#   - 已存在 Release  -> 仅 edit 更新 title/body, 不动 assets (幂等)
#   - 不存在 Release  -> create, 可选附加本地 assets
#
# 用法:
#   scripts/release-github.sh <tag>                       # 例: v3.4.3
#   scripts/release-github.sh <tag> --draft               # 创建为 draft
#   scripts/release-github.sh <tag> --prerelease          # 标记为预发布
#   scripts/release-github.sh <tag> --latest              # 标记为 latest (默认会自动判断)
#   scripts/release-github.sh <tag> --assets=path1,path2  # 上传本地附件
#   scripts/release-github.sh <tag> --force-recreate      # 删除现有 Release 后重建 (会丢失 assets)
#   scripts/release-github.sh <tag> --single              # 仅用当前 tag 单文件 docs/changelog/<tag>.md
#   scripts/release-github.sh <tag> --since=vX.Y.Z        # 强制指定起点 tag, 区间 (since, tag]
#   scripts/release-github.sh <tag> --dry-run             # 只打印不执行
#
# Release body 生成策略 (默认):
#   * 自动找出"上一个已发布的 GitHub Release"作为起点 (LAST_RELEASED)
#   * 直接读 git log (LAST_RELEASED, <tag>] 区间所有 commit, 调用共享脚本
#     scripts/_changelog_gen.py 重新分类/去重/格式化, 输出一份完整 changelog
#   * 这与 release.sh 生成单 tag changelog 用的是同一份格式逻辑, 区别仅在区间不同
#   * 中间漏发的 tag 不会被分段折叠展示, 而是"当成本次发布的一部分"扁平铺开
#   * 想退回到原行为 (只用 docs/changelog/<tag>.md 文件) 加 --single
#   * 想强制起点加 --since=vX.Y.Z
#
# 凭据:
#   .release 文件中的 RELEASE_GH_TOKEN 会被加载到 GH_TOKEN 供 gh CLI 使用。
#   如果已经 gh auth login, 直接复用本机凭据即可。
#
# 依赖: git, gh (GitHub CLI), python3
# =============================================================================
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()   { echo -e "${GREEN}[OK]${NC}    $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $*"; }
err()  { echo -e "${RED}[ERR]${NC}   $*" >&2; }
die()  { err "$*"; exit 1; }

# ---------- 参数 ----------
TAG="${1:-}"
DRY_RUN=false
DRAFT=false
PRERELEASE=false
LATEST_FLAG=""    # "" / "--latest=true" / "--latest=false"
ASSETS=""
FORCE_RECREATE=false
SINGLE=false
SINCE_TAG=""
shift || true
for arg in "$@"; do
  case "$arg" in
    --dry-run)        DRY_RUN=true ;;
    --draft)          DRAFT=true ;;
    --prerelease)     PRERELEASE=true; LATEST_FLAG="--latest=false" ;;
    --latest)         LATEST_FLAG="--latest=true" ;;
    --no-latest)      LATEST_FLAG="--latest=false" ;;
    --assets=*)       ASSETS="${arg#*=}" ;;
    --force-recreate) FORCE_RECREATE=true ;;
    --single)         SINGLE=true ;;
    --since=*)        SINCE_TAG="${arg#*=}" ;;
    *) die "未知参数: $arg" ;;
  esac
done

[[ -z "$TAG" ]] && die "用法: $0 <tag> [--draft] [--prerelease] [--single] [--since=vX.Y.Z] [--assets=a,b] [--force-recreate] [--dry-run]"
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-[a-zA-Z0-9.]+)?$ ]] \
  || die "tag 格式应为 vX.Y.Z 或 vX.Y.Z-suffix, 实际: $TAG"

# 自动 prerelease: tag 含连字符后缀 (例如 v3.5.0-beta.1) 默认视为预发布
if ! $PRERELEASE && [[ "$TAG" == *-* ]]; then
  warn "tag $TAG 含预发布后缀, 自动标记为 --prerelease"
  PRERELEASE=true
  LATEST_FLAG="--latest=false"
fi

# ---------- 路径 ----------
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
CHANGELOG_FILE="$REPO_ROOT/docs/changelog/${TAG}.md"
RELEASE_ENV_FILE="$REPO_ROOT/.release"

# ---------- 加载 .release 凭据 ----------
if [[ -f "$RELEASE_ENV_FILE" ]]; then
  log "加载 $RELEASE_ENV_FILE"
  while IFS= read -r raw_line || [[ -n "$raw_line" ]]; do
    line="${raw_line%%#*}"
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [[ -z "$line" ]] && continue
    if [[ "$line" =~ ^[A-Za-z_][A-Za-z0-9_]*= ]]; then
      key="${line%%=*}"
      val="${line#*=}"
      if [[ "$val" =~ ^\"(.*)\"$ ]] || [[ "$val" =~ ^\'(.*)\'$ ]]; then
        val="${BASH_REMATCH[1]}"
      fi
      if [[ -z "${!key:-}" ]]; then
        export "$key=$val"
      fi
    fi
  done < "$RELEASE_ENV_FILE"
fi

# gh 优先使用 GH_TOKEN; 若 .release 配置了 RELEASE_GH_TOKEN, 自动同步
if [[ -z "${GH_TOKEN:-}" && -n "${RELEASE_GH_TOKEN:-}" ]]; then
  export GH_TOKEN="$RELEASE_GH_TOKEN"
fi

# ---------- 前置校验 ----------
command -v gh >/dev/null 2>&1 \
  || die "未安装 gh CLI, 请先安装: brew install gh (mac) / winget install --id GitHub.cli (Windows)"

if [[ -z "${GH_TOKEN:-}" ]]; then
  gh auth status >/dev/null 2>&1 \
    || die "gh 未登录且未提供 GH_TOKEN, 请先 gh auth login 或在 .release 配置 RELEASE_GH_TOKEN"
fi

if $SINGLE; then
  [[ -f "$CHANGELOG_FILE" ]] \
    || die "未找到 $CHANGELOG_FILE, 请先执行 scripts/release.sh $TAG 生成单 tag changelog"
fi

# 远端 tag 必须存在
if ! git ls-remote --tags --exit-code origin "refs/tags/$TAG" >/dev/null 2>&1; then
  die "远端 origin 上不存在 tag $TAG, 请先 git push origin $TAG"
fi

# ---------- 计算起点 tag (上一个已发布 Release) ----------
# 起点 tag 选取顺序:
#   1) 命令行 --since=vX.Y.Z 指定
#   2) --single 模式: 不需要起点
#   3) 自动: 取上一个已存在的 GitHub Release 的 tagName (语义版本 < $TAG 中最大的)
#   4) 没有任何 Release -> 起点为空, 收集 $TAG 之前所有 commit
START_TAG=""
if [[ -n "$SINCE_TAG" ]]; then
  START_TAG="$SINCE_TAG"
  log "起点 tag (来自 --since): $START_TAG"
elif $SINGLE; then
  log "--single 模式: 直接使用 $TAG 单文件 changelog"
else
  set +e
  RELEASES_JSON="$(gh release list --limit 100 --json tagName,isDraft 2>/dev/null)"
  rc=$?
  set -e
  if [[ $rc -eq 0 && -n "$RELEASES_JSON" && "$RELEASES_JSON" != "[]" ]]; then
    START_TAG="$(TARGET_TAG="$TAG" RELEASES_JSON="$RELEASES_JSON" python3 <<'PYEOF'
import os, json, re
target = os.environ.get("TARGET_TAG", "")
raw    = os.environ.get("RELEASES_JSON", "[]")
def vkey(t):
    m = re.match(r'^v(\d+)\.(\d+)\.(\d+)(?:-(.+))?$', t)
    if not m: return None
    x, y, z, suf = int(m[1]), int(m[2]), int(m[3]), m[4]
    return (x, y, z, 0 if suf else 1, suf or "")
data = json.loads(raw)
tk = vkey(target)
candidates = []
for r in data:
    if r.get("isDraft"): continue
    name = r.get("tagName", "")
    k = vkey(name)
    if k and tk and k < tk:
        candidates.append((k, name))
if candidates:
    candidates.sort()
    print(candidates[-1][1])
PYEOF
)"
    if [[ -n "$START_TAG" ]]; then
      log "起点 tag (上一个已发布 Release): $START_TAG"
    else
      log "未找到比 $TAG 更早的已发布 Release, 将聚合 $TAG 之前所有 commit"
    fi
  else
    log "尚无任何 GitHub Release, 将聚合 $TAG 之前所有 commit"
  fi
fi

# 如果指定了起点 tag, 校验它在 git 里能解析
if [[ -n "$START_TAG" ]]; then
  if ! git rev-parse --verify "$START_TAG" >/dev/null 2>&1; then
    warn "本地不存在 tag $START_TAG, 尝试从 origin 拉取..."
    git fetch --depth 1 origin "refs/tags/$START_TAG:refs/tags/$START_TAG" 2>/dev/null \
      || die "无法解析起点 tag $START_TAG (本地与 origin 都没有), 请检查 --since 参数"
  fi
fi

# ---------- 生成扁平 changelog (notes 文件) ----------
NOTES_FILE="$(mktemp -t release-notes.XXXXXX.md)"
trap 'rm -f "$NOTES_FILE"' EXIT

if $SINGLE; then
  # --single: 完全使用 docs/changelog/<tag>.md 内容
  log "使用单 tag 模式: $CHANGELOG_FILE"
  cat "$CHANGELOG_FILE" > "$NOTES_FILE"
else
  # 默认: 调用共享 changelog 生成器, 区间 (START_TAG, TAG]
  SHARED_GEN="$REPO_ROOT/scripts/_changelog_gen.py"
  [[ -f "$SHARED_GEN" ]] || die "缺少共享脚本: $SHARED_GEN"

  # 解析 OWNER_REPO (用于 commit/issue 链接)
  OWNER_REPO_FOR_GEN="$(git config --get remote.origin.url 2>/dev/null \
    | sed -E 's#.*github.com[:/](.*)\.git#\1#' || true)"

  if [[ -n "$START_TAG" ]]; then
    GIT_RANGE="${START_TAG}..${TAG}"
    RANGE_LABEL_FOR_GEN="$START_TAG"
    log "git log 区间: $GIT_RANGE"
  else
    GIT_RANGE="$TAG"
    RANGE_LABEL_FOR_GEN="initial"
    log "无起点 tag, 使用 $TAG 之前所有 commit"
  fi

  RAW_LOG="$(git log "$GIT_RANGE" --no-merges --pretty=format:'%H%x09%s%x09%an' || true)"
  COMMIT_COUNT="$(echo "$RAW_LOG" | grep -c $'\t' || true)"
  log "区间内 commit 数: $COMMIT_COUNT"

  # 调用共享生成器
  PARSED="$(NEW_VERSION="$TAG" RANGE_LABEL="$RANGE_LABEL_FOR_GEN" \
    USE_EMOJI=1 TAG_LIMIT=999 \
    OWNER_REPO="$OWNER_REPO_FOR_GEN" \
    python3 "$SHARED_GEN" <<<"$RAW_LOG")"

  # 抽取 MARK_CHANGELOG_FILE 段
  CHANGELOG_BODY="$(awk '
    $0 == "MARK_CHANGELOG_FILE" { capture=1; next }
    capture && $0 == "MARK_END" { exit }
    capture { print }
  ' <<<"$PARSED")"

  [[ -z "$CHANGELOG_BODY" ]] && die "共享生成器输出为空, 检查 git 区间是否有效"
  echo "$CHANGELOG_BODY" > "$NOTES_FILE"
fi

# ---------- 解析 assets ----------
ASSET_ARGS=()
if [[ -n "$ASSETS" ]]; then
  IFS=',' read -ra ASSET_LIST <<< "$ASSETS"
  for a in "${ASSET_LIST[@]}"; do
    a="${a#"${a%%[![:space:]]*}"}"
    a="${a%"${a##*[![:space:]]}"}"
    [[ -z "$a" ]] && continue
    [[ -f "$a" ]] || die "asset 不存在: $a"
    ASSET_ARGS+=("$a")
  done
fi

# ---------- 状态预检 ----------
RELEASE_EXISTS=false
ASSET_COUNT=0
set +e
release_json="$(gh release view "$TAG" --json tagName,assets,isDraft,isPrerelease 2>/dev/null)"
rc=$?
set -e
if [[ $rc -eq 0 && -n "$release_json" ]]; then
  RELEASE_EXISTS=true
  ASSET_COUNT="$(python3 -c "import json,sys; print(len(json.loads(sys.argv[1]).get('assets',[])))" "$release_json" 2>/dev/null || echo 0)"
fi

OWNER_REPO="$(git config --get remote.origin.url | sed -E 's#.*github.com[:/](.*)\.git#\1#')"
RELEASE_URL="https://github.com/${OWNER_REPO}/releases/tag/${TAG}"

# ---------- 组装 gh release 参数 ----------
GH_ARGS=( --title "$TAG" --notes-file "$NOTES_FILE" )
$DRAFT      && GH_ARGS+=( --draft )
$PRERELEASE && GH_ARGS+=( --prerelease )
[[ -n "$LATEST_FLAG" ]] && GH_ARGS+=( "$LATEST_FLAG" )

echo
log "Release 状态预检:"
echo "    Tag         : $TAG"
echo "    Exists      : $RELEASE_EXISTS"
echo "    Assets      : $ASSET_COUNT"
if $SINGLE; then
  echo "    Mode        : --single (单文件 docs/changelog/${TAG}.md)"
elif [[ -n "$START_TAG" ]]; then
  echo "    Range       : ${START_TAG} → ${TAG}"
else
  echo "    Range       : (initial) → ${TAG}"
fi
echo "    Notes file  : $NOTES_FILE ($(wc -l <"$NOTES_FILE" | tr -d ' ') lines)"
echo "    Draft       : $DRAFT"
echo "    Prerelease  : $PRERELEASE"
[[ ${#ASSET_ARGS[@]} -gt 0 ]] && echo "    Local assets: ${ASSET_ARGS[*]}"
echo "    URL         : $RELEASE_URL"
echo

if $DRY_RUN; then
  warn "--dry-run, 仅打印计划:"
  if $RELEASE_EXISTS && ! $FORCE_RECREATE; then
    echo "    gh release edit \"$TAG\" --notes-file \"$NOTES_FILE\" --title \"$TAG\""
  elif $RELEASE_EXISTS && $FORCE_RECREATE; then
    echo "    gh release delete \"$TAG\" --yes"
    echo "    gh release create \"$TAG\" ${GH_ARGS[*]} ${ASSET_ARGS[*]:-}"
  else
    echo "    gh release create \"$TAG\" ${GH_ARGS[*]} ${ASSET_ARGS[*]:-}"
  fi
  echo
  log "聚合后的 notes 内容预览 (前 40 行):"
  head -40 "$NOTES_FILE" | sed 's/^/    /'
  exit 0
fi

# ---------- 执行 ----------
if $RELEASE_EXISTS; then
  if $FORCE_RECREATE; then
    warn "Release $TAG 已存在, 按 --force-recreate 删除后重建 (会丢失 $ASSET_COUNT 个 assets)"
    gh release delete "$TAG" --yes
    log "重建 Release $TAG..."
    if [[ ${#ASSET_ARGS[@]} -gt 0 ]]; then
      gh release create "$TAG" "${GH_ARGS[@]}" "${ASSET_ARGS[@]}"
    else
      gh release create "$TAG" "${GH_ARGS[@]}"
    fi
  else
    log "Release $TAG 已存在, 仅更新 title/body (保留 $ASSET_COUNT 个 assets)..."
    EDIT_ARGS=( --title "$TAG" --notes-file "$NOTES_FILE" )
    $DRAFT      && EDIT_ARGS+=( --draft=true )      || EDIT_ARGS+=( --draft=false )
    $PRERELEASE && EDIT_ARGS+=( --prerelease=true ) || EDIT_ARGS+=( --prerelease=false )
    gh release edit "$TAG" "${EDIT_ARGS[@]}"
    # 追加上传额外 assets (如有)
    if [[ ${#ASSET_ARGS[@]} -gt 0 ]]; then
      log "追加上传 ${#ASSET_ARGS[@]} 个 asset..."
      gh release upload "$TAG" "${ASSET_ARGS[@]}" --clobber
    fi
  fi
else
  log "创建 Release $TAG..."
  if [[ ${#ASSET_ARGS[@]} -gt 0 ]]; then
    gh release create "$TAG" "${GH_ARGS[@]}" "${ASSET_ARGS[@]}"
  else
    gh release create "$TAG" "${GH_ARGS[@]}"
  fi
fi

ok "Release $TAG 处理完成 ✅"
echo "    $RELEASE_URL"
