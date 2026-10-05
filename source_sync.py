"""One-file source drafts, conservative numeric bindings, and reviewed writes."""
from __future__ import annotations

import difflib
import hashlib
import math
import os
import re
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

EXTENSIONS = {'.c', '.h', '.cpp', '.hpp', '.cc', '.cxx'}
MAX_BYTES = 2 * 1024 * 1024
NUMBER = r'[+-]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?[fFlL]?'
MASK = re.compile(r'//[^\n]*|/\*[\s\S]*?\*/|"(?:\\[\s\S]|[^"\\])*"|\'(?:\\[\s\S]|[^\'\\])*\'')
ASSIGN = re.compile(r'(?<![\w.>])(?P<name>\.?[A-Za-z_]\w*(?:(?:\.|->)[A-Za-z_]\w*)*)[ \t]*=(?!=)[ \t]*(?P<value>' + NUMBER + r')[ \t]*(?=[;,}])')
DEFINE = re.compile(r'^[ \t]*#[ \t]*define[ \t]+(?P<name>[A-Za-z_]\w*)[ \t]+(?P<value>' + NUMBER + r')[ \t]*$', re.M)


@dataclass(frozen=True)
class Candidate:
    name: str
    kind: str
    line: int
    start: int
    end: int
    literal: str

    @property
    def identity(self):
        return self.kind, self.name, self.line

    @property
    def label(self):
        return f'{self.name} = {self.literal}  · 第 {self.line} 行'


def scan_candidates(text: str):
    """Ignore comments/strings; never evaluate expressions or guess a PID loop."""
    masked = MASK.sub(lambda m: ''.join('\n' if c == '\n' else ' ' for c in m[0]), text)
    candidates = []
    for kind, regex in [('宏', DEFINE), ('赋值', ASSIGN)]:
        for match in regex.finditer(masked):
            start, end = match.span('value')
            candidates.append(Candidate(match['name'], kind, text.count('\n', 0, start) + 1,
                                        start, end, text[start:end]))
    return sorted(candidates, key=lambda c: c.start)


def replace_gains(text, bindings, gains):
    if set(bindings) != {'kp', 'ki', 'kd'} or set(gains) != {'kp', 'ki', 'kd'}:
        raise ValueError('请分别绑定 P、I、D 三个源码位置')
    current = scan_candidates(text)
    edits = []
    for key, candidate in bindings.items():
        if candidate not in current:
            raise ValueError('代码已改动，请重新识别并核对参数绑定')
        value = float(gains[key])
        if not math.isfinite(value):
            raise ValueError('PID 参数必须是有限数值')
        suffix = candidate.literal[-1] if candidate.literal[-1] in 'fFlL' else ''
        literal = format(value, '.9g' if suffix.lower() == 'f' else '.17g')
        if suffix and '.' not in literal and 'e' not in literal.lower():
            literal += '.0'
        edits.append((candidate.start, candidate.end, literal + suffix))
    if len({(start, end) for start, end, _ in edits}) != 3:
        raise ValueError('P、I、D 不能绑定到同一个源码位置')
    for start, end, literal in sorted(edits, reverse=True):
        text = text[:start] + literal + text[end:]
    return text


def checked_path(root, path):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('请选择有效的工程文件夹')
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('只能打开所选工程文件夹内的文件')
    if path.suffix.lower() not in EXTENSIONS:
        raise ValueError('目前支持 C/C++ 源码和头文件')
    return root, path


def decode_source(raw):
    if len(raw) > MAX_BYTES or b'\0' in raw:
        raise ValueError('文件过大或不是支持的文本源码（上限 2 MB）')
    if raw.startswith(b'\xef\xbb\xbf'):
        encoding = 'utf-8-sig'
    else:
        try:
            raw.decode('utf-8')
            encoding = 'utf-8'
        except UnicodeDecodeError:
            encoding = 'gb18030'
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError as error:
        raise ValueError('无法识别文件编码，请先在 IDE 中转换为 UTF-8') from error
    if text.encode(encoding) != raw:
        raise ValueError('文件编码无法无损往返，请先转换为 UTF-8')
    remainder = text.replace('\r\n', '')
    if '\r' in remainder or ('\r\n' in text and '\n' in remainder):
        raise ValueError('文件混用了换行格式，请先在 IDE 中统一换行')
    newline = '\r\n' if '\r\n' in text else '\n'
    return text.replace('\r\n', '\n'), encoding, newline


@dataclass(frozen=True)
class SourceFile:
    root: Path
    path: Path
    raw: bytes
    text: str
    encoding: str
    newline: str

    @classmethod
    def open(cls, root, path):
        root, path = checked_path(root, path)
        with path.open('rb') as handle:
            raw = handle.read(MAX_BYTES + 1)
        text, encoding, newline = decode_source(raw)
        return cls(root, path, raw, text, encoding, newline)

    def check_current(self):
        root, path = checked_path(self.root, self.path)
        with path.open('rb') as handle:
            current = handle.read(MAX_BYTES + 1)
        if root != self.root or path != self.path or current != self.raw:
            raise ValueError('文件已被 IDE 或其他程序修改；未写入。请重新载入并核对修改')
        if not (path.stat().st_mode & stat.S_IWRITE):
            raise ValueError('源码文件为只读，请在工程中解除只读后重新载入')

    def plan(self, text):
        self.check_current()
        if not text.strip():
            raise ValueError('不能保存空白源码文件')
        if '\r' in text or '\0' in text:
            raise ValueError('代码草稿包含不支持的字符')
        try:
            raw = text.replace('\n', self.newline).encode(self.encoding)
        except UnicodeEncodeError as error:
            raise ValueError('新增字符不兼容原文件编码，请在 IDE 中转换为 UTF-8') from error
        if len(raw) > MAX_BYTES:
            raise ValueError('代码草稿超过 2 MB')
        if raw == self.raw:
            raise ValueError('没有需要保存的修改')
        relative = self.path.relative_to(self.root).as_posix()
        lines = difflib.unified_diff(self.text.splitlines(keepends=True), text.splitlines(keepends=True),
                                    fromfile=relative + '（磁盘）', tofile=relative + '（草稿）')
        diff = ''.join(line if line.endswith('\n') else line + '\n\\ No newline at end of file\n' for line in lines)
        return WritePlan(self, text, raw, diff)


@dataclass(frozen=True)
class WritePlan:
    source: SourceFile
    text: str
    raw: bytes
    diff: str

    def apply(self, backups):
        """Only called by the explicit save button in the change preview."""
        self.source.check_current()
        backups = Path(backups)
        backups.mkdir(parents=True, exist_ok=True)
        identity = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex
        backup = backups / (identity + '-' + self.source.path.name + '.bak')
        with backup.open('xb') as handle:
            handle.write(self.source.raw)
            handle.flush()
            os.fsync(handle.fileno())
        temporary = self.source.path.with_name('.' + self.source.path.name + '.pidlab-' + identity + '.tmp')
        try:
            with temporary.open('xb') as handle:
                handle.write(self.raw)
                handle.flush()
                os.fsync(handle.fileno())
            self.source.check_current()
            os.replace(temporary, self.source.path)
        finally:
            # A single explicit temporary file; never remove a folder or a batch.
            if temporary.exists():
                temporary.unlink()
        if self.source.path.read_bytes() != self.raw:
            raise ValueError('保存后的文件与预览不同，请核对外部修改；原文件备份：' + str(backup))
        return backup


def digest_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()
