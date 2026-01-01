; iHIM Dashboard Hotkey
; Win+Alt+Ctrl opens iHIM in default browser
;
; To use:
;   1. Install AutoHotkey v2: https://www.autohotkey.com/
;   2. Double-click this file to run
;   3. Add to startup folder for auto-run on login
;
; Startup folder: shell:startup (Win+R, type shell:startup)

#Requires AutoHotkey v2.0

; Win+Alt+Ctrl opens iHIM dashboard
^!#Space:: {
    Run "http://localhost:7777"
}

; Alternative: Win+Alt+Ctrl+I (if you want a letter key too)
; ^!#i:: {
;     Run "http://localhost:7777"
; }
