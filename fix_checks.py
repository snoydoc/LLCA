import pathlib

f = pathlib.Path('D:/LLMCodeAgent/check_env.py')
txt = f.read_text(encoding='utf-8-sig')

old6 = '        tm.log_operation(tx, OpType.PATCH_FILE, str(tmp_f), rollback_data=b"x = 1\\n")'
new6_lines = [
    '        def _noop():',
    '            pass',
    '',
    '        tm.log_operation(',
    '            target_path=tmp_f,',
    '            op_type=OpType.PATCH_FILE,',
    '            execute_func=_noop,',
    '        )',
]

old7 = '    patcher = SmartPatcher()'
new7_lines = [
    '    with tempfile.TemporaryDirectory() as td_patch:',
    '        ws_patch = Path(td_patch)',
    '        (ws_patch / "mod.py").write_text(code, encoding="utf-8")',
    '        patcher = SmartPatcher(workspace=ws_patch)',
]

# Patch 6
if old6 in txt:
    txt = txt.replace(old6, '\n'.join(new6_lines))
    print('BLOC 6 patche')
else:
    print('BLOC 6 NON TROUVE')

# Patch 7
if old7 in txt:
    txt = txt.replace(old7, '\n'.join(new7_lines))
    print('BLOC 7 patche')
else:
    print('BLOC 7 NON TROUVE')

# Patch commit(tx) -> commit()
txt = txt.replace('        tm.commit(tx)', '        tm.commit()')

# Patch apply_patch(source=
old_ap = '    result = patcher.apply_patch(source=code, patch_type="add_function", code=patch_code)'
new_ap = '        result = patcher.apply_patch(file_path="mod.py", patch_type="add_function", code=patch_code)'
if old_ap in txt:
    txt = txt.replace(old_ap, new_ap)
    print('apply_patch patche')
else:
    print('apply_patch NON TROUVE')

f.write_text(txt, encoding='utf-8-sig')
print('DONE')
