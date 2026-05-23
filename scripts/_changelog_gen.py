#!/usr/bin/env python3
# =============================================================================
# 共享 changelog 生成器
#
# 功能:
#   读取 stdin 上的 git log (--pretty=format:'%H%x09%s%x09%an'), 清洗 / 去重 /
#   分类后输出三段标记数据:
#     MARK_CHANGELOG_FILE ... MARK_END   完整 changelog (markdown), 用作
#                                        docs/changelog/<tag>.md 与 GitHub
#                                        Release body
#     MARK_TAG            ... MARK_END   git tag annotated message (TAG_LIMIT
#                                        条上限, 含 emoji/ASCII 切换)
#     MARK_HIGHLIGHTS     ... MARK_END   最多 5 条核心高亮 (Breaking > Added
#                                        > Fixed > ...)
#
# 环境变量:
#   NEW_VERSION    : 当前发布的 tag (例: v3.4.2-beta.5)
#   RANGE_LABEL    : 区间起点标签, 用于 Range / Compare 链接 (例: v3.4.2-beta.0
#                    或 v3.4.1; 找不到时为空字符串)
#   OWNER_REPO     : github owner/repo (例: joneezhu/NasTools), 用于生成 commit
#                    与 issue 链接, 留空则退化为纯文本
#   USE_EMOJI      : "1" 用 emoji 类目图标, "0" 用 ASCII; 默认 "1"
#   TAG_LIMIT      : tag message 中条目上限, 默认 12
#
# 由 scripts/release.sh 与 scripts/release-github.sh 共享调用, 保证
# "新 tag 单文件" 与 "GitHub Release 聚合" 两条路径用同一份输出格式。
# =============================================================================
import os, re, sys, collections, datetime

raw = sys.stdin.read().strip()
if not raw:
    # 没有 commit, 仍然要输出 MARK 段 (空内容), 让上游脚本能正常解析
    new_version = os.environ.get("NEW_VERSION", "")
    today = datetime.date.today().isoformat()
    prev_label = os.environ.get("RANGE_LABEL", "previous")
    print("MARK_CHANGELOG_FILE")
    print(f"# Release {new_version}")
    print()
    print(f"- **Date**: {today}")
    print(f"- **Range**: {prev_label} → {new_version}")
    print(f"- **Commits**: 0 kept / 0 total")
    print()
    print("---")
    print()
    print("## Changed")
    print()
    print("- 区间内无 commit (可能是直接重打 tag)")
    print("MARK_END")
    print("MARK_TAG")
    print(f"# Release {new_version}")
    print()
    print(f"- **Date**: {today}")
    print(f"- **Range**: {prev_label} → {new_version}")
    print()
    print("---")
    print()
    print("_无 commit (可能是直接重打 tag)_")
    print("MARK_END")
    print("MARK_HIGHLIGHTS")
    print("MARK_END")
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
    s = re.sub(r"^[a-zA-Z]+(\([^)]+\))?!?:\s*", "", subject).strip()
    if s:
        s = s[0].upper() + s[1:]
    return s


OWNER_REPO = os.environ.get("OWNER_REPO", "").strip()


def commit_link(short, full):
    if not OWNER_REPO:
        return short
    return f"[`{short}`](https://github.com/{OWNER_REPO}/commit/{full})"


def linkify_issues(text):
    if not OWNER_REPO:
        return text

    def repl(m):
        num = m.group(1)
        return f"[#{num}](https://github.com/{OWNER_REPO}/issues/{num})"

    return re.sub(r"(?:(?<=^)|(?<=[\s(\[,;:]))(?:#|GH-)(\d+)\b", repl, text)


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
    buckets[cat].append((norm, short, h))

new_version = os.environ["NEW_VERSION"]
today = datetime.date.today().isoformat()

# ---------- MARK_CHANGELOG_FILE ----------
file_lines = [
    f"# Release {new_version}",
    "",
    f"- **Date**: {today}",
    f"- **Range**: {os.environ.get('RANGE_LABEL', 'previous')} → {new_version}",
    f"- **Commits**: {sum(len(v) for v in buckets.values())} kept / {len(all_short_hashes)} total",
]
prev_label = os.environ.get("RANGE_LABEL", "")
if OWNER_REPO and prev_label and prev_label.startswith("v"):
    file_lines.append(
        f"- **Compare**: [{prev_label}...{new_version}]"
        f"(https://github.com/{OWNER_REPO}/compare/{prev_label}...{new_version})"
    )
file_lines += ["", "---", ""]
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

# ---------- MARK_TAG ----------
# 注意: GitHub tag 页 (releases/tag/<t>) 会把 annotated tag message 当 markdown 渲染,
#       所以这里输出和 MARK_CHANGELOG_FILE 同款的 markdown, 让 commit / PR 都能跳转
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

tag_lines = [
    f"# Release {new_version}",
    "",
    f"- **Date**: {today}",
    f"- **Range**: {prev_label} → {new_version}",
    f"- **Commits**: {total_kept} kept / {total_raw} total"
    + (f"  ·  Categories: {len(non_empty_cats)}" if non_empty_cats else ""),
]
if OWNER_REPO and prev_label and prev_label.startswith("v"):
    tag_lines.append(
        f"- **Compare**: [{prev_label}...{new_version}]"
        f"(https://github.com/{OWNER_REPO}/compare/{prev_label}...{new_version})"
    )
tag_lines += ["", "---", ""]

total_in_tag = 0
overflow = False
for cat, items in buckets.items():
    if not items:
        continue
    tag_lines.append(f"## {cat_label(cat)} ({len(items)})")
    tag_lines.append("")
    for norm, short, full in items:
        if total_in_tag >= TAG_LIMIT:
            overflow = True
            break
        tag_lines.append(f"- {linkify_issues(norm)} ({commit_link(short, full)})")
        total_in_tag += 1
    tag_lines.append("")
    if overflow:
        break

if overflow:
    remaining = total_kept - total_in_tag
    tag_lines.append("---")
    tag_lines.append("")
    tag_lines.append(
        f"_… +{remaining} more entries — see [`docs/changelog/{new_version}.md`]"
        f"(https://github.com/{OWNER_REPO}/blob/{new_version}/docs/changelog/{new_version}.md)_"
        if OWNER_REPO else
        f"_… +{remaining} more entries — see docs/changelog/{new_version}.md_"
    )

print("MARK_TAG")
print("\n".join(tag_lines).rstrip())
print("MARK_END")

# ---------- MARK_HIGHLIGHTS ----------
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
