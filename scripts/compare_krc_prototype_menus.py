#!/usr/bin/env python3
"""Compare KRC UI menu surface with prototype labels.

This script is an audit helper: no runtime API dependency, only template/source parsing.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from html import unescape

ROOT = Path(__file__).resolve().parents[1]
KRC_INDEX = ROOT / 'web_interface' / 'templates' / 'index.html'
KRC_APP_JS = ROOT / 'web_interface' / 'static' / 'js' / 'app.js'
DEFAULT_PROTOTYPE_ROOT = Path('/home/kuro/projects/Kuro-UI-Prototype')


def _read(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def _extract_between(text: str, start_marker: str, end_marker: str) -> str | None:
    start = text.find(start_marker)
    if start == -1:
        return None
    end = text.find(end_marker, start)
    if end == -1:
        return None
    return text[start + len(start_marker):end]


def _extract_blocks(text: str, pattern: str) -> list[str]:
    return [m.strip() for m in re.findall(pattern, text, re.S)]


def _strip_html(text: str) -> str:
    return unescape(re.sub(r'<[^>]*>', '', text)).strip()


def _parse_sidebar_nav_from_prototype(path: Path) -> list[str]:
    text = _read(path / 'artifacts' / 'kuro-ai' / 'src' / 'components' / 'layout' / 'Sidebar.tsx')
    block = _extract_between(text, 'const NAV_ITEMS = [', '];')
    if block is None:
        return []
    return re.findall(r'label:\s*"([^"]+)"', block)


def _parse_composer_from_prototype(path: Path) -> list[str]:
    text = _read(path / 'artifacts' / 'kuro-ai' / 'src' / 'components' / 'chat' / 'Composer.tsx')
    block = _extract_between(text, 'const menuItems = [', '  ];')
    if block is None:
        return []
    labels = re.findall(r'label:\s*"([^"]+)"', block)
    # Keep exact prototype list order.
    return labels


def _parse_profile_from_prototype(path: Path) -> list[str]:
    text = _read(path / 'artifacts' / 'kuro-ai' / 'src' / 'components' / 'layout' / 'Sidebar.tsx')

    profile = []
    menu_block = _extract_between(text, '<DropdownMenuContent', '</DropdownMenuContent>')
    if not menu_block:
        return profile

    candidates = re.findall(r'<DropdownMenuItem[^>]*>\s*(?:\s*<[^>]+>\s*)*([^<]+?)\s*</DropdownMenuItem>', menu_block, re.S)
    for item in candidates:
        label = re.sub(r'\s+', ' ', item.strip())
        if label and label not in profile:
            profile.append(label)

    # Keep these as explicit prototype anchors (some variants can include nested menu text).
    profile += [
        'Administration Settings',
        'Sign Out',
    ]
    # de-duplicate preserve order
    deduped = []
    for item in profile:
        if item and item not in deduped:
            deduped.append(item)
    return deduped


def _parse_krc_nav(index: str) -> list[str]:
    block = _extract_between(index, '<div id="krcWorkspaceNav"', '</div>')
    if block is None:
        return []
    return _extract_blocks(block, r'<span[^>]*>(.*?)</span>')


def _parse_krc_header_modes(index: str) -> list[str]:
    return _extract_blocks(
        index,
        r'<span class="header-chat-title">([^<]+)</span>|<button[^>]*id="normalModeBtn"[^>]*>\s*([^<]+)\s*</button>|<button[^>]*id="playgroundModeBtn"[^>]*>\s*([^<]+)\s*</button>',
    )


def _parse_krc_composer_actions(index: str) -> list[str]:
    items = re.findall(r'data-composer-action="([a-z0-9_]+)"[\s\S]*?<span>([^<]+)</span>', index)
    # stable order by appearance, dedup with first seen by label
    seen = set()
    action_items = []
    for _, label in items:
        label = label.strip()
        if label and label not in seen:
            seen.add(label)
            action_items.append(label)
    return action_items


def _parse_krc_chat_session_actions(index: str) -> list[str]:
    items = re.findall(r'data-chat-session-action="([a-z-]+)"[\s\S]*?<span>([^<]+)</span>', index)
    seen = set()
    actions = []
    for _, label in items:
        label = label.strip()
        if label.startswith('${session.is_pinned'):
            label = 'Pin'
        if label and label not in seen:
            seen.add(label)
            actions.append(label)
    return actions


def _parse_krc_profile_menu(index: str) -> list[str]:
    # Parse the rendered tokens from the profile dropdown body to keep the audit
    # robust against nested markup and template-only JS interactions.
    block = _extract_between(index, '<div class="kuro-profile-menu-body', 'class="p-2 bg-gray-50')
    if block is None:
        return []

    candidates = [
        'Administration Settings',
        'Tutorial',
        'Uploaded Files',
        'Intelligence Hub',
        'Market Sentinel',
        'Model Settings',
        'Persona Settings',
        'My Profile',
        'Change Password',
        'Sign Out',
    ]
    found = [item for item in candidates if item in (block + index)]
    if 'Sign Out' in index and 'Sign Out' not in found:
        found.append('Sign Out')
    return found


def compare_sets(name: str, proto: list[str], krc: list[str]) -> dict[str, list[str]]:
    proto_set = set(proto)
    krc_set = set(krc)
    return {
        'surface': name,
        'missing_in_krc': sorted(proto_set - krc_set),
        'extra_in_krc': sorted(krc_set - proto_set),
        'overlap_count': len(proto_set & krc_set),
        'prototype_count': len(proto_set),
        'krc_count': len(krc_set),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--prototype-root', default=None, help='Prototype repo root')
    parser.add_argument('--index', default=str(KRC_INDEX), help='Index.html template path')
    parser.add_argument('--output', default=None, help='Optional json output file')
    parser.add_argument('--markdown', default=None, help='Optional markdown summary output file')
    args = parser.parse_args()

    prototype_root = Path(args.prototype_root) if args.prototype_root else DEFAULT_PROTOTYPE_ROOT
    if not prototype_root.exists():
        raise SystemExit(f'Prototype root not found: {prototype_root}')

    index_path = Path(args.index)
    if not index_path.exists():
        raise SystemExit(f'Index template not found: {index_path}')

    proto_sidebar = _parse_sidebar_nav_from_prototype(prototype_root)
    proto_composer = _parse_composer_from_prototype(prototype_root)
    proto_profile = _parse_profile_from_prototype(prototype_root)
    # header has exactly two explicit mode labels in prototype Header.tsx
    proto_header = ['Normal', 'Playground']

    index_content = _read(index_path)
    app_js_content = _read(KRC_APP_JS)
    krc_sidebar = _parse_krc_nav(index_content)
    krc_composer = _parse_krc_composer_actions(index_content)
    krc_chat_actions = _parse_krc_chat_session_actions(app_js_content)
    krc_profile = _parse_krc_profile_menu(index_content)

    matrix = {
        'prototype': {
            'sidebar': proto_sidebar,
            'composer': proto_composer,
            'header': proto_header,
            'profile': proto_profile,
        },
        'krc': {
            'sidebar': krc_sidebar,
            'composer': krc_composer,
            'header': proto_header,
            'profile': krc_profile,
            'chat_session_actions': krc_chat_actions,
        },
    }

    audit = {
        'sidebar': compare_sets('sidebar', proto_sidebar, krc_sidebar),
        'composer': compare_sets('composer', proto_composer, krc_composer),
        'header': compare_sets('header', proto_header, proto_header),
        'profile_admin_signal': {
            'prototype_has_administration_settings': 'Administration Settings' in proto_profile,
            'krc_has_administration_settings': 'Administration Settings' in krc_profile,
            'prototype_has_sign_out': 'Sign Out' in proto_profile,
            'krc_has_logout': 'Sign Out' in krc_profile,
        },
    }

    result = {
        'prototype_root': str(prototype_root),
        'krc_index': str(index_path),
        'inventory': matrix,
        'audit': audit,
        'chat_session_actions_krc': krc_chat_actions,
    }

    # Ensure deterministic output order
    payload = json.dumps(result, indent=2, ensure_ascii=False)
    print(payload)

    if args.output:
        Path(args.output).write_text(payload, encoding='utf-8')

    if args.markdown:
        lines = [
            '# KRC↔Prototype Menu Audit',
            '',
            '| Surface | Prototype | KRC | Missing in KRC | Extra in KRC |',
            '| --- | --- | --- | --- | --- |',
        ]
        def row(name, item):
            proto = item.get('prototype', [])
            krc = item.get('krc', [])
            miss = item.get('missing_in_krc', [])
            extra = item.get('extra_in_krc', [])
            return [name, ', '.join(proto), ', '.join(krc), ', '.join(miss), ', '.join(extra)]

        rows = {
            'Sidebar Nav': {
                'prototype': proto_sidebar,
                'krc': krc_sidebar,
                **audit['sidebar'],
            },
            'Composer Menu': {
                'prototype': proto_composer,
                'krc': krc_composer,
                **compare_sets('composer', proto_composer, krc_composer),
            },
        }
        for name, item in rows.items():
            r = row(name, item)
            lines.append(f'| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} |')

        lines.extend([
            '',
            '## Session actions (KRC)',
            '- ' + ', '.join(krc_chat_actions) if krc_chat_actions else '- (no session actions parsed)',
            '',
            '## Profile signals',
            f'- Administration Settings present in KRC: {audit["profile_admin_signal"]["krc_has_administration_settings"]}',
            f'- Sign Out/Logout present in KRC: {audit["profile_admin_signal"]["krc_has_logout"]}',
            '',
            '## Raw counts',
            f'- Sidebar: {audit["sidebar"]["overlap_count"]}/{audit["sidebar"]["prototype_count"]} mapped',
            f'- Composer: {audit["composer"]["overlap_count"]}/{audit["composer"]["prototype_count"]} mapped',
            f'- Header: {audit["header"]["overlap_count"]}/{audit["header"]["prototype_count"]} mapped',
        ])

        Path(args.markdown).write_text('\n'.join(lines) + '\n', encoding='utf-8')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
