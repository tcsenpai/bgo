# Fish completions for bgo - lightweight background process manager
# Install: cp bgo.fish ~/.config/fish/completions/

# Helper: list registered process names
function __bgo_process_names
    bgo status --json 2>/dev/null | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if isinstance(data, list):
        for p in data:
            print(p.get('name', ''))
except: pass
" 2>/dev/null
end

# Disable file completions by default
complete -c bgo -f

# Subcommands (first positional arg only)
complete -c bgo -n '__fish_use_subcommand' -a start -d 'Start a process'
complete -c bgo -n '__fish_use_subcommand' -a open -d 'Alias for start'
complete -c bgo -n '__fish_use_subcommand' -a stop -d 'Stop a process'
complete -c bgo -n '__fish_use_subcommand' -a kill -d 'Alias for stop'
complete -c bgo -n '__fish_use_subcommand' -a restart -d 'Restart a process'
complete -c bgo -n '__fish_use_subcommand' -a restart-stopped -d 'Restart stopped processes'
complete -c bgo -n '__fish_use_subcommand' -a restart-last -d 'Restart most recent first'
complete -c bgo -n '__fish_use_subcommand' -a status -d 'Show process status'
complete -c bgo -n '__fish_use_subcommand' -a ls -d 'Alias for status'
complete -c bgo -n '__fish_use_subcommand' -a list -d 'Alias for status'
complete -c bgo -n '__fish_use_subcommand' -a logs -d 'View process logs'
complete -c bgo -n '__fish_use_subcommand' -a follow -d 'Follow logs (tail -f)'
complete -c bgo -n '__fish_use_subcommand' -a tail -d 'Alias for follow'
complete -c bgo -n '__fish_use_subcommand' -a watch -d 'Attach watcher to process'
complete -c bgo -n '__fish_use_subcommand' -a unwatch -d 'Detach watcher'
complete -c bgo -n '__fish_use_subcommand' -a clean -d 'Remove stopped processes'
complete -c bgo -n '__fish_use_subcommand' -a delete -d 'Delete a process'
complete -c bgo -n '__fish_use_subcommand' -a rm -d 'Alias for delete'
complete -c bgo -n '__fish_use_subcommand' -a resurrect -d 'Restart all previously running'
complete -c bgo -n '__fish_use_subcommand' -a autostart -d 'Manage login autostart'
complete -c bgo -n '__fish_use_subcommand' -a tray -d 'Launch system tray icon'

# Process name completions for commands that take a name
complete -c bgo -n '__fish_seen_subcommand_from stop kill' -a '(__bgo_process_names)' -d 'process'
complete -c bgo -n '__fish_seen_subcommand_from restart' -a '(__bgo_process_names)' -d 'process'
complete -c bgo -n '__fish_seen_subcommand_from watch' -a '(__bgo_process_names)' -d 'process'
complete -c bgo -n '__fish_seen_subcommand_from unwatch' -a '(__bgo_process_names)' -d 'process'
complete -c bgo -n '__fish_seen_subcommand_from logs follow tail' -a '(__bgo_process_names)' -d 'process'
complete -c bgo -n '__fish_seen_subcommand_from delete rm' -a '(__bgo_process_names)' -d 'process'
complete -c bgo -n '__fish_seen_subcommand_from status ls list' -a '(__bgo_process_names)' -d 'process'

# Flags
complete -c bgo -n '__fish_seen_subcommand_from stop kill' -s f -l force -d 'Force kill (SIGKILL)'
complete -c bgo -n '__fish_seen_subcommand_from start open' -l cwd -d 'Working directory'
complete -c bgo -n '__fish_seen_subcommand_from start open' -s w -l watch -d 'Auto-restart on crash'
complete -c bgo -n '__fish_seen_subcommand_from start open watch' -l interval -d 'Poll interval (seconds)'
complete -c bgo -n '__fish_seen_subcommand_from start open watch' -l min-uptime -d 'Crash threshold (seconds)'
complete -c bgo -n '__fish_seen_subcommand_from start open watch' -l on-fast-crash -a 'backoff stop retry' -d 'Fast-crash policy'
complete -c bgo -n '__fish_seen_subcommand_from watch' -l reset -d 'Reset watch config'
complete -c bgo -n '__fish_seen_subcommand_from restart' -l reset-counters -d 'Zero restart counter'
complete -c bgo -n '__fish_seen_subcommand_from restart-stopped restart-last' -s a -l all -d 'Restart all (no prompt)'
complete -c bgo -n '__fish_seen_subcommand_from status ls list' -s w -l watch -d 'Auto-refresh mode'
complete -c bgo -n '__fish_seen_subcommand_from status ls list' -l interval -d 'Refresh interval (seconds)'
complete -c bgo -n '__fish_seen_subcommand_from status ls list' -l json -d 'JSON output'
complete -c bgo -n '__fish_seen_subcommand_from status ls list' -l plain -d 'Plain ASCII rendering'
complete -c bgo -n '__fish_seen_subcommand_from status ls list' -l fancy -d 'Unicode box-drawing'
complete -c bgo -n '__fish_seen_subcommand_from logs follow tail' -s f -l follow -d 'Follow output'
complete -c bgo -n '__fish_seen_subcommand_from logs follow tail' -s n -l lines -d 'Number of lines'
complete -c bgo -n '__fish_seen_subcommand_from logs follow tail' -l stdout -d 'Stdout only'
complete -c bgo -n '__fish_seen_subcommand_from logs follow tail' -l stderr -d 'Stderr only'
complete -c bgo -n '__fish_seen_subcommand_from logs' -l watcher -d 'Watcher log'
complete -c bgo -n '__fish_seen_subcommand_from delete rm' -s y -l yes -d 'Skip confirmation'
complete -c bgo -n '__fish_seen_subcommand_from delete rm' -l keep-logs -d 'Keep log files'
complete -c bgo -n '__fish_seen_subcommand_from tray' -l poll -d 'Poll interval (seconds)'
complete -c bgo -n '__fish_seen_subcommand_from tray' -l auto-install -d 'Install PySide6 if missing'

# Autostart subcommands
complete -c bgo -n '__fish_seen_subcommand_from autostart' -a install -d 'Install autostart entry'
complete -c bgo -n '__fish_seen_subcommand_from autostart' -a uninstall -d 'Remove autostart entry'
complete -c bgo -n '__fish_seen_subcommand_from autostart' -a status -d 'Show install state'
