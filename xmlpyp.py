#!/bin/env python

import argparse
import ast
import io
import re
import sys
import traceback
from typing import TextIO


class PythonError(RuntimeError):
    """Error raised from Python processing instructions."""

    def __init__(self, e: Exception):
        super().__init__(e)

    def get_exc(self) -> Exception:
        return self.args[0]

    def print(self, file=sys.stderr, no_color=False):
        if not no_color and not file.isatty():
            no_color = True
        if not no_color:
            print('\x1b[1;31m', file=file)

        e = self.get_exc()
        tb = e.__traceback__
        if isinstance(e, SyntaxError):
            traceback.print_exception(None, e, None, file=file)
        else:
            traceback.print_exception(None, e, tb, file=file)

        if not no_color:
            print('\x1b[0m', file=file)


class XmlError(RuntimeError):
    """XML syntax error."""

    def __init__(self, msg: str):
        super().__init__(msg)

    def print(self, file=sys.stderr, no_color=False):
        if not no_color and not file.isatty():
            no_color = True
        if not no_color:
            print('\x1b[1;31m', file=file)

        print('Bad XML syntax:', self.args[0])

        if not no_color:
            print('\x1b[0m', file=file)


class Processor:
    """Python processing instruction processor."""

    class _AstLineNoModifier(ast.NodeVisitor):
        def __init__(self, lineno_add: int):
            self.lineno_add = lineno_add

        def visit(self, node):
            if hasattr(node, 'lineno') and isinstance(node.lineno, int):
                node.lineno += self.lineno_add
                if hasattr(node, 'end_lineno'):
                    assert isinstance(node.end_lineno, int)
                    node.end_lineno += self.lineno_add
            self.generic_visit(node)

        def __call__(self, node: ast.AST):
            self.visit(node)

    @staticmethod
    def _open_file_w(path_or_stream: TextIO | str) -> tuple[TextIO, bool]:
        if hasattr(path_or_stream, 'write'):
            return path_or_stream, False
        return open(path_or_stream, 'w'), True

    @staticmethod
    def _open_file_r(path_or_stream: TextIO | str) -> tuple[TextIO, bool]:
        if hasattr(path_or_stream, 'read'):
            return path_or_stream, False
        return open(path_or_stream, 'r'), True

    @staticmethod
    def _close_file(f: tuple[TextIO, bool]):
        if f[1]:
            f[0].close()

    @staticmethod
    def _clear_StringIO(x: io.StringIO):
        x.truncate(0)
        x.seek(0)

    def __init__(self, file: TextIO | str, pi_target='py'):
        self.out_stream, self.out_stream_flag = Processor._open_file_w(file)
        self.pi_target = pi_target

        self.code_buffer = io.StringIO()  # Python code from PI
        self.print_buffer = io.StringIO() # fake stdout

        pattern_pi_beg = r'<\?\s*' + pi_target + r'\s'
        pattern_pi_tag = pattern_pi_beg + r'(.+?)\?>'
        self.pattern_pi_beg = re.compile(pattern_pi_beg)
        self.pattern_pi_tag = re.compile(pattern_pi_tag)

        self.exec_globals = {}

    def __del__(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_tp, exc_val, exc_tb):
        self.close()

    def __call__(self, file: TextIO | str):
        self.input(file)

    def close(self):
        if self.out_stream:
            Processor._close_file((self.out_stream, self.out_stream_flag))
            self.out_stream = None
        self.code_buffer.close()
        self.print_buffer.close()

    def exec_py(self, source: str | TextIO, file_name: str, line_num: int = 1):
        if not isinstance(source, str):
            source = source.read()

        line_num_offset = line_num - 1
        assert line_num_offset >= 0

        try:
            src_ast = ast.parse(source, file_name)
        except SyntaxError as e:
            if line_num_offset:
                if isinstance(e.lineno, int):
                    e.lineno += line_num_offset
                    if hasattr(e, 'end_lineno'):
                        assert isinstance(e.end_lineno, int)
                        e.end_lineno += line_num_offset
                if isinstance(e.text, str):
                    try:
                        current_lineno = 0
                        error_lineno = e.lineno
                        with open(file_name, 'r') as f:
                            for line_text in f:
                                current_lineno += 1
                                if (current_lineno == error_lineno):
                                    e.text = line_text
                                    break
                    except:
                        pass
            raise PythonError(e)
        if line_num_offset:
            Processor._AstLineNoModifier(line_num_offset)(src_ast)

        code = compile(src_ast, file_name, 'exec')
        try:
            exec(code, self.exec_globals)
        except Exception as e:
            raise PythonError(e)

    def input(self, file: TextIO | str):
        assert self.out_stream is not None

        in_stream, in_stream_flag = Processor._open_file_r(file)
        in_stream_filename = \
            file if isinstance(file, str) else getattr(file, 'name', '?')
        orig_stdout, sys.stdout = sys.stdout, self.print_buffer

        try:
            line_num = 0
            in_pi_tag = False
            this_pi_tag_beg_ln = 0

            def exec_and_dump(src, to_stream: TextIO | None) -> None | str:
                Processor._clear_StringIO(self.print_buffer)
                self.exec_py(src, in_stream_filename, this_pi_tag_beg_ln)
                res = self.print_buffer.getvalue()
                if to_stream is None:
                    return res
                else:
                    to_stream.write(res)

            for line in in_stream:
                line_num += 1

                if in_pi_tag: # reading multi-line PI
                    if (end_pos := line.find('?>')) == -1: # multi-line PI continues
                        self.code_buffer.write(line)
                        continue
                    else: # multi-line PI ends
                        self.code_buffer.write(line[:end_pos])
                        self.code_buffer.seek(0)
                        exec_and_dump(self.code_buffer, self.out_stream)
                        in_pi_tag = False
                        this_pi_tag_beg_ln = 0
                        line = line[end_pos + 2:]

                if line.find('<?') != -1: # possible PI in current line
                    this_pi_tag_beg_ln = line_num
                    line = self.pattern_pi_tag \
                        .sub(lambda m: exec_and_dump(m[1], None), line)
                    if (m := self.pattern_pi_beg.search(line)): # multi-line PI
                        beg_pos = m.end(0) - 1 # last char is a whitespace
                        assert line[beg_pos].isspace()
                        in_pi_tag = True
                        this_pi_tag_beg_ln = line_num
                        Processor._clear_StringIO(self.code_buffer)
                        self.code_buffer.write(line[beg_pos:])
                        line = line[:m.start()]
                self.out_stream.write(line)

            if in_pi_tag:
                raise XmlError(
                    'processing instruction starting from '
                    f'line {this_pi_tag_beg_ln} was never closed'
                )

        finally:
            sys.stdout = orig_stdout
            Processor._close_file((in_stream, in_stream_flag))

def main():
    ap = argparse.ArgumentParser(
        description='XML Python processing instruction processor. '
        'It executes the Python code in Python PI tags (see option "-T") '
        'and replace the tags with contents written to "sys.stdout".'
    )
    ap.add_argument(
        '-t', '--pi-target', default='py',
        help='the processing instruction target for Python code; '
        'default PITarget is "py", i.e. using tags like "<?py ... ?>"',
    )
    ap.add_argument(
        '-c', '--exec', metavar='COMMAND', action='append',
        help='command to execute before handling files',
    )
    ap.add_argument(
        '--no-color', action='store_true',
        help='do not use different color when printing error messages',
    )
    ap.add_argument(
        '-o', '--output', metavar='FILE', default=sys.stdout,
        help='path to the output file; omitting means printing to stdout',
    )
    ap.add_argument(
        'INPUT', nargs='*',
        help='source XML file; omitting means reading from stdin',
    )
    args = ap.parse_args()
    pi_tgt = args.pi_target
    cmds = args.exec
    no_color = args.no_color
    output = args.output
    inputs = args.INPUT
    del ap, args

    try:
        with Processor(output, pi_tgt) as p:
            if cmds:
                for c in cmds:
                    p.exec_py(c, '<command-line>')
            if inputs:
                for i in inputs:
                    p(i)
            else:
                p(sys.stdin)
    except (PythonError, XmlError) as e:
        e.print(no_color=no_color)


if __name__ == '__main__':
    main()
