"""Audit C12: spending, integrity and approval checks must survive python -O."""
import ast
from pathlib import Path


def test_studio_code_has_no_assert_statements():
    offenders=[]
    for path in sorted(Path(__file__).resolve().parent.parent.joinpath('studio').glob('*.py')):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,ast.Assert):offenders.append(f'{path.name}:{node.lineno}')
    assert offenders==[]
