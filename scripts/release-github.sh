#!/usr/bin/env bash
# =============================================================================
# NAStool GitHub Release 自动化脚本
#
# 功能:
#   读取 docs/changelog/<tag>.md 作为 body, 调用 gh release create / edit
#   创建或更新 GitHub Release。
#
#   - 已存在 Release  -> 仅 edit 更新 title/body, 不动 assets (幂等)
#   - 不存在 Release  -> create, 可选附加本地 assets
#   - 单 tag changelog 不存在 -> 报错退出, 提示先跑 release.sh
#
# 用法:
#   scripts/release-github.sh <tag>                       # 例: v3.4.3
#   scripts/release-github.sh <tag> --draft               # 创建为 draft
#   scripts/release-github.sh <tag> --prerelease          # 标记为预发布
#   scripts/release-github.sh <tag> --latest              # 标记为 latest (默认会自动判断)
#   scripts/release-github.sh <tag> --assets=path1,path2  # 上传本地附件
#   scripts/release-github.sh <tag> --force-recreate      # 删除现有 Release 后重建 (会丢失 assets)
#   scripts/release-github.sh <tag> --dry-run             # 只打印不执行
#
# 凭据:
#   .release 文件中的 RELEASE_GH_TOKEN 会被加载到 GH_TOKEN 供 gh CLI 使用。
#   如果已经 gh auth login, 直接复用本机凭据即可。
#
# 依赖: git, gh (GitHub CLI)
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
    *) die "未知参数: $arg" ;;
  esac
done

[[ -z "$TAG" ]] && die "用法: $0 <tag> [--draft] [--prerelease] [--assets=a,b] [--force-recreate] [--dry-run]"
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

[[ -f "$CHANGELOG_FILE" ]] \
  || die "未找到 $CHANGELOG_FILE, 请先执行 scripts/release.sh $TAG 生成单 tag changelog"

# 远端 tag 必须存在
if ! git ls-remote --tags --exit-code origin "refs/tags/$TAG" >/dev/null 2>&1; then
  die "远端 origin 上不存在 tag $TAG, 请先 git push origin $TAG"
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
GH_ARGS=( --title "$TAG" --notes-file "$CHANGELOG_FILE" )
$DRAFT      && GH_ARGS+=( --draft )
$PRERELEASE && GH_ARGS+=( --prerelease )
[[ -n "$LATEST_FLAG" ]] && GH_ARGS+=( "$LATEST_FLAG" )

echo
log "Release 状态预检:"
echo "    Tag         : $TAG"
echo "    Exists      : $RELEASE_EXISTS"
echo "    Assets      : $ASSET_COUNT"
echo "    Changelog   : docs/changelog/${TAG}.md ($(wc -l <"$CHANGELOG_FILE" | tr -d ' ') lines)"
echo "    Draft       : $DRAFT"
echo "    Prerelease  : $PRERELEASE"
[[ ${#ASSET_ARGS[@]} -gt 0 ]] && echo "    Local assets: ${ASSET_ARGS[*]}"
echo "    URL         : $RELEASE_URL"
echo

if $DRY_RUN; then
  warn "--dry-run, 仅打印计划:"
  if $RELEASE_EXISTS && ! $FORCE_RECREATE; then
    echo "    gh release edit \"$TAG\" --notes-file \"$CHANGELOG_FILE\" --title \"$TAG\""
  elif $RELEASE_EXISTS && $FORCE_RECREATE; then
    echo "    gh release delete \"$TAG\" --yes"
    echo "    gh release create \"$TAG\" ${GH_ARGS[*]} ${ASSET_ARGS[*]:-}"
  else
    echo "    gh release create \"$TAG\" ${GH_ARGS[*]} ${ASSET_ARGS[*]:-}"
  fi
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
    EDIT_ARGS=( --title "$TAG" --notes-file "$CHANGELOG_FILE" )
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
