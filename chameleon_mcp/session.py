_session: dict = {
    "explored": {},
    "skills": {},
    "grown": {},
    "morphed_tools": [],      # names of dynamically registered proxy tools
    "current_form": None,     # server_id currently morphed into
    "connections": {},        # persistent connections: {pool_key: {name, command, pid, ...}}
    "stats": {
        "total_calls": 0,
        "tokens_sent": 0,
        "tokens_received": 0,
        "tokens_saved_browse": 0,
    },
}

session = _session
