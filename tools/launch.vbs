Set fso = CreateObject("Scripting.FileSystemObject")
Set f = fso.CreateTextFile("D:\coding\dsh-ptforge\fixtures\probe\vbs_ok.txt", True)
f.WriteLine "wscript ran"
f.Close
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -File ""D:\coding\dsh-ptforge\tools\ptkeys.ps1""", 0, False

