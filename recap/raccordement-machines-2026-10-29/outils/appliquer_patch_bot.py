"""Render a focused bot.py update without exporting or overwriting private defaults.

This tool never replaces the input file, starts the bot, or reads any .env/DB.
Review the generated --output and keep existing data/configuration on deployment.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path


def render(source, patch):
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    targets = {node.name: node for node in tree.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}
    edits = []
    missing = []
    for item in patch['nodes']:
        text = item['source']
        assert hashlib.sha256(text.encode()).hexdigest() == item['sha256'], 'Payload modified'
        ast.parse(text)
        node = targets.get(item['name'])
        if node is None:
            missing.append(text)
            continue
        start = min([node.lineno] + [d.lineno for d in node.decorator_list])
        edits.append((start - 1, node.end_lineno, text))
    for start, end, text in sorted(edits, reverse=True):
        lines[start:end] = text.splitlines(keepends=True)
    result = ''.join(lines)
    if missing:
        tree = ast.parse(result)
        anchor = next(node for node in tree.body if isinstance(node, ast.ClassDef)
                      and node.name == patch['anchor'])
        lines = result.splitlines(keepends=True)
        lines[anchor.lineno - 1:anchor.lineno - 1] = ['\n\n'.join(missing) + '\n\n']
        result = ''.join(lines)
    tree = ast.parse(result)
    installed = any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == 'install_website_bridge' for node in ast.walk(tree))
    if not installed:
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and node.func.attr == 'run'
                 and isinstance(node.func.value, ast.Name) and node.func.value.id == 'bot'
                 and any(isinstance(arg, ast.Name) and arg.id == 'DISCORD_TOKEN' for arg in node.args)]
        if len(calls) != 1:
            raise ValueError('Expected one bot.run(DISCORD_TOKEN); review bootstrap manually.')
        lines = result.splitlines(keepends=True)
        position = calls[0].lineno - 1
        indent = lines[position][:len(lines[position]) - len(lines[position].lstrip())]
        boot = ''.join(indent + line[4:] if line.startswith('    ') else line
                       for line in patch['bootstrap_lines'].splitlines(keepends=True))
        lines[position:position] = [boot]
        result = ''.join(lines)
    compile(result, '<rendered-bot-update>', 'exec')
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('target', type=Path)
    parser.add_argument('patch', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.target.resolve() == args.output.resolve():
        raise SystemExit('Choose a separate --output; review before replacing the live file.')
    original = args.target.read_text(encoding='utf-8')
    rendered = render(original, json.loads(args.patch.read_text(encoding='utf-8')))
    args.output.write_text(rendered, encoding='utf-8')
    print('Rendered and syntax checked. No bot/service/configuration executed or changed.')


if __name__ == '__main__':
    main()
