#!/usr/bin/env bash
# Bash completions for bgo
# Install: source this in ~/.bashrc or copy to /etc/bash_completion.d/

_bgo() {
    local cur prev commands
    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"
    commands="start open stop kill restart restart-stopped restart-last status ls list logs follow tail watch unwatch clean delete rm resurrect autostart tray"

    # First arg: complete subcommands
    if [[ $COMP_CWORD -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "$commands" -- "$cur") )
        return 0
    fi

    # Commands that take a process name as next arg
    local name_commands="stop kill restart watch unwatch logs follow tail delete rm"
    local subcmd="${COMP_WORDS[1]}"

    # If completing after a name-taking command and no flag started
    if [[ " $name_commands " == *" $subcmd "* ]] && [[ $COMP_CWORD -eq 2 ]] && [[ ! "$cur" == -* ]]; then
        local names
        names=$(bgo status --json 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if isinstance(data, list):
        for p in data:
            print(p.get('name', ''))
except: pass
" 2>/dev/null)
        COMPREPLY=( $(compgen -W "$names" -- "$cur") )
        return 0
    fi

    # Status also optionally takes a name
    if [[ "$subcmd" == @(status|ls|list) ]] && [[ $COMP_CWORD -eq 2 ]] && [[ ! "$cur" == -* ]]; then
        local names
        names=$(bgo status --json 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if isinstance(data, list):
        for p in data:
            print(p.get('name', ''))
except: pass
" 2>/dev/null)
        COMPREPLY=( $(compgen -W "$names" -- "$cur") )
        return 0
    fi

    # Flag completions
    case "$subcmd" in
        stop|kill)
            COMPREPLY=( $(compgen -W "-f --force" -- "$cur") ) ;;
        start|open)
            COMPREPLY=( $(compgen -W "--cwd -w --watch --interval --min-uptime --on-fast-crash" -- "$cur") ) ;;
        restart)
            COMPREPLY=( $(compgen -W "--reset-counters" -- "$cur") ) ;;
        restart-stopped|restart-last)
            COMPREPLY=( $(compgen -W "-a --all" -- "$cur") ) ;;
        status|ls|list)
            COMPREPLY=( $(compgen -W "-w --watch --interval --json --plain --fancy" -- "$cur") ) ;;
        logs)
            COMPREPLY=( $(compgen -W "-f --follow -n --lines --stdout --stderr --watcher" -- "$cur") ) ;;
        follow|tail)
            COMPREPLY=( $(compgen -W "-n --lines --stdout --stderr" -- "$cur") ) ;;
        watch)
            COMPREPLY=( $(compgen -W "--interval --min-uptime --on-fast-crash --reset" -- "$cur") ) ;;
        delete|rm)
            COMPREPLY=( $(compgen -W "-y --yes --keep-logs" -- "$cur") ) ;;
        autostart)
            COMPREPLY=( $(compgen -W "install uninstall status --tray" -- "$cur") ) ;;
        tray)
            COMPREPLY=( $(compgen -W "--poll --auto-install" -- "$cur") ) ;;
    esac

    return 0
}
complete -F _bgo bgo
