; Block Alt+Space from triggering Windows system menu
; The capture widget's pynput listener still receives the keypress
#NoEnv
#SingleInstance Force
#Persistent

!Space::return  ; Consume Alt+Space, do nothing
