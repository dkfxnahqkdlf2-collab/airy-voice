"""
core/folder_picker.py
독립 프로세스에서 실행되는 윈도우 최상단(TopMost) 폴더 선택기
Streamlit 멀티스레드 충돌을 100% 방지하고 브라우저 맨 위에 팝업을 띄웁니다.
"""
import os
import sys

def main():
    init_dir = sys.argv[1] if len(sys.argv) > 1 else "captures"
    abs_init = os.path.abspath(init_dir) if os.path.exists(init_dir) else os.path.abspath(".")

    # 1순위: Tkinter with TopMost parent
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.wm_attributes("-topmost", 1)
        root.focus_force()

        path = filedialog.askdirectory(
            parent=root,
            initialdir=abs_init,
            title="Flow 9:16 세로 이미지 저장 폴더를 선택하세요",
        )
        root.destroy()
        if path:
            print(os.path.normpath(path))
            return
    except Exception:
        pass

    # 2순위 Fallback: PowerShell FolderBrowserDialog
    try:
        import subprocess
        ps_path = abs_init.replace('\\', '/')
        ps_code = f"""
Add-Type -AssemblyName System.Windows.Forms
$form = New-Object System.Windows.Forms.Form
$form.TopMost = $true
$form.StartPosition = 'Manual'
$form.Location = New-Object System.Drawing.Point(-2000, -2000)
$form.Show()
$f = New-Object System.Windows.Forms.FolderBrowserDialog
$f.SelectedPath = '{ps_path}'
$f.Description = '이미지를 저장할 폴더를 선택하세요'
if ($f.ShowDialog($form) -eq [System.Windows.Forms.DialogResult]::OK) {{
    Write-Output $f.SelectedPath
}}
$form.Close()
"""
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_code],
            capture_output=True,
            text=True,
            timeout=25,
        )
        out = r.stdout.strip()
        if out and os.path.isdir(out):
            print(os.path.normpath(out))
            return
    except Exception:
        pass

if __name__ == "__main__":
    main()
