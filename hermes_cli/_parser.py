"""
Top-level argparse construction for the hermes CLI.

Lives in its own module so other modules (e.g. ``relaunch.py``) can
introspect the parser to discover which flags exist without running the
``main`` fn.

Only the top-level parser and the ``chat`` subparser live here. Every other
subparser (model, gateway, sessions, …) is built inline in ``main.py``
because its dispatch is tightly coupled to module-level ``cmd_*`` functions.
"""

import argparse
from agent.i18n import t as _t


def _tr(key: str, **kwargs) -> str:
    """Translate a CLI help string."""
    return _t(f"cli.{key}", **kwargs)


class _TranslatedHelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Custom HelpFormatter that translates the -h/--help option text."""
    
    def _format_action_invocation(self, action):
        """Override to translate the help option text."""
        if action.option_strings == ['-h', '--help']:
            # Translate the help text for -h/--help
            action.help = _tr("option_help")
        return super()._format_action_invocation(action)


def add_translated_subparser(subparsers, name, **kwargs):
    """Add a subparser with translated help formatter.
    
    This is a helper function to ensure all subcommands use the
    _TranslatedHelpFormatter for consistent i18n support.
    """
    if 'formatter_class' not in kwargs:
        kwargs['formatter_class'] = _TranslatedHelpFormatter
    return subparsers.add_parser(name, **kwargs)


# `--profile` / `-p` is consumed by ``main._apply_profile_override`` before
# argparse runs (it sets ``HERMES_HOME`` and strips itself from ``sys.argv``),
# so it isn't on the parser. Listed here so all "carry over on relaunch"
# metadata lives in one file.
PRE_ARGPARSE_INHERITED_FLAGS: list[tuple[str, bool]] = [
    ("--profile", True),
    ("-p", True),
]


def _inherited_flag(parser, *args, **kwargs):
    """Register a flag that ``hermes_cli.relaunch`` should carry over when
    the CLI re-execs itself (e.g. after ``sessions browse`` picks a session,
    or after the setup wizard launches chat).

    Equivalent to ``parser.add_argument(...)`` plus tagging the resulting
    Action with ``inherit_on_relaunch = True`` so the relaunch table builder
    can find it via introspection.
    """
    action = parser.add_argument(*args, **kwargs)
    action.inherit_on_relaunch = True
    return action


_EPILOGUE = """
Examples:
    hermes                        Start interactive chat
    hermes chat -q "Hello"        Single query mode
    hermes -c                     Resume the most recent session
    hermes -c "my project"        Resume a session by name (latest in lineage)
    hermes --resume <session_id>  Resume a specific session by ID
    hermes setup                  Run setup wizard
    hermes logout                 Clear stored authentication
    hermes auth add <provider>    Add a pooled credential
    hermes auth list              List pooled credentials
    hermes auth remove <p> <t>    Remove pooled credential by index, id, or label
    hermes auth reset <provider>  Clear exhaustion status for a provider
    hermes model                  Select default model
    hermes fallback [list]        Show fallback provider chain
    hermes fallback add           Add a fallback provider (same picker as `hermes model`)
    hermes fallback remove        Remove a fallback provider from the chain
    hermes config                 View configuration
    hermes config edit            Edit config in $EDITOR
    hermes config set model gpt-4 Set a config value
    hermes gateway                Run messaging gateway
    hermes -s hermes-agent-dev,github-auth
    hermes -w                     Start in isolated git worktree
    hermes gateway install        Install gateway background service
    hermes sessions list          List past sessions
    hermes sessions browse        Interactive session picker
    hermes sessions rename ID T   Rename/title a session
    hermes logs                   View agent.log (last 50 lines)
    hermes logs -f                Follow agent.log in real time
    hermes logs errors            View errors.log
    hermes logs --since 1h        Lines from the last hour
    hermes debug share             Upload debug report for support
    hermes update                 Update to latest version
    hermes dashboard              Start web UI dashboard (port 9119)
    hermes dashboard --stop       Stop running dashboard processes
    hermes dashboard --status     List running dashboard processes

For more help on a command:
    hermes <command> --help
"""


def build_top_level_parser():
    """Build the top-level parser, the subparsers action, and the ``chat`` subparser.

    Returns ``(parser, subparsers, chat_parser)``. The caller wires
    ``chat_parser.set_defaults(func=cmd_chat)`` and continues registering
    other subparsers via ``subparsers.add_parser(...)``.
    """
    # Build translated epilogue
    examples_title = _tr("epilogue_examples_title")
    for_more_help = _tr("epilogue_for_more_help")
    
    # Get all example lines with translations
    example_lines = [
        _tr("epilogue_example_hermes"),
        _tr("epilogue_example_chat_q"),
        _tr("epilogue_example_c"),
        _tr("epilogue_example_c_name"),
        _tr("epilogue_example_resume"),
        _tr("epilogue_example_setup"),
        _tr("epilogue_example_logout"),
        _tr("epilogue_example_auth_add"),
        _tr("epilogue_example_auth_list"),
        _tr("epilogue_example_auth_remove"),
        _tr("epilogue_example_auth_reset"),
        _tr("epilogue_example_model"),
        _tr("epilogue_example_fallback"),
        _tr("epilogue_example_fallback_add"),
        _tr("epilogue_example_fallback_remove"),
        _tr("epilogue_example_config"),
        _tr("epilogue_example_config_edit"),
        _tr("epilogue_example_config_set"),
        _tr("epilogue_example_gateway"),
        _tr("epilogue_example_skills"),
        _tr("epilogue_example_worktree"),
        _tr("epilogue_example_gateway_install"),
        _tr("epilogue_example_sessions_list"),
        _tr("epilogue_example_sessions_browse"),
        _tr("epilogue_example_sessions_rename"),
        _tr("epilogue_example_logs"),
        _tr("epilogue_example_logs_f"),
        _tr("epilogue_example_logs_errors"),
        _tr("epilogue_example_logs_since"),
        _tr("epilogue_example_debug_share"),
        _tr("epilogue_example_update"),
        _tr("epilogue_example_dashboard"),
        _tr("epilogue_example_dashboard_stop"),
        _tr("epilogue_example_dashboard_status"),
    ]
    
    # Build the translated epilogue
    translated_epilogue = f"\n{examples_title}\n"
    for line in example_lines:
        translated_epilogue += f"{line}\n"
    translated_epilogue += f"\n{for_more_help}\n    hermes <command> --help\n"
    
    parser = argparse.ArgumentParser(
        prog="hermes",
        description=_tr("description"),
        formatter_class=_TranslatedHelpFormatter,
        epilog=translated_epilogue,
    )

    parser.add_argument(
        "--version", "-V", action="store_true", help=_tr("option_version")
    )
    parser.add_argument(
        "-z",
        "--oneshot",
        metavar="PROMPT",
        default=None,
        help=_tr("option_oneshot"),
    )
    # --model / --provider are accepted at the top level so they can pair
    # with -z without needing the `chat` subcommand.  If neither -z nor a
    # subcommand consumes them, they fall through harmlessly as None.
    # Mirrors `hermes chat --model ... --provider ...` semantics.
    _inherited_flag(
        parser,
        "-m",
        "--model",
        default=None,
        help=_tr("option_model"),
    )
    _inherited_flag(
        parser,
        "--provider",
        default=None,
        help=_tr("option_provider"),
    )
    parser.add_argument(
        "-t",
        "--toolsets",
        default=None,
        help=_tr("option_toolsets"),
    )
    parser.add_argument(
        "--resume",
        "-r",
        metavar="SESSION",
        default=None,
        help=_tr("option_resume"),
    )
    parser.add_argument(
        "--continue",
        "-c",
        dest="continue_last",
        nargs="?",
        const=True,
        default=None,
        metavar="SESSION_NAME",
        help=_tr("option_continue"),
    )
    parser.add_argument(
        "--worktree",
        "-w",
        action="store_true",
        default=False,
        help=_tr("option_worktree"),
    )
    _inherited_flag(
        parser,
        "--accept-hooks",
        action="store_true",
        default=False,
        help=_tr("option_accept_hooks"),
    )
    _inherited_flag(
        parser,
        "--skills",
        "-s",
        action="append",
        default=None,
        help=_tr("option_skills"),
    )
    _inherited_flag(
        parser,
        "--yolo",
        action="store_true",
        default=False,
        help=_tr("option_yolo"),
    )
    _inherited_flag(
        parser,
        "--pass-session-id",
        action="store_true",
        default=False,
        help=_tr("option_pass_session_id"),
    )
    _inherited_flag(
        parser,
        "--ignore-user-config",
        action="store_true",
        default=False,
        help=_tr("option_ignore_user_config"),
    )
    _inherited_flag(
        parser,
        "--ignore-rules",
        action="store_true",
        default=False,
        help=_tr("option_ignore_rules"),
    )
    _inherited_flag(
        parser,
        "--tui",
        action="store_true",
        default=False,
        help=_tr("option_tui"),
    )
    _inherited_flag(
        parser,
        "--dev",
        dest="tui_dev",
        action="store_true",
        default=False,
        help=_tr("option_dev"),
    )

    subparsers = parser.add_subparsers(dest="command", help=_tr("subcommand_help"))

    # =========================================================================
    # chat command
    # =========================================================================
    chat_parser = add_translated_subparser(
        subparsers,
        "chat",
        help=_tr("chat_help"),
        description=_tr("chat_description"),
    )
    chat_parser.add_argument(
        "-q", "--query", help=_tr("chat_option_query")
    )
    chat_parser.add_argument(
        "--image", help=_tr("chat_option_image")
    )
    _inherited_flag(
        chat_parser,
        "-m", "--model", help=_tr("chat_option_model"),
    )
    chat_parser.add_argument(
        "-t", "--toolsets", help=_tr("chat_option_toolsets")
    )
    _inherited_flag(
        chat_parser,
        "-s",
        "--skills",
        action="append",
        default=argparse.SUPPRESS,
        help=_tr("option_skills"),
    )
    _inherited_flag(
        chat_parser,
        "--provider",
        # No `choices=` here: user-defined providers from config.yaml `providers:`
        # are also valid values, and runtime resolution (resolve_runtime_provider)
        # handles validation/error reporting consistently with the top-level
        # `--provider` flag.
        default=None,
        help=_tr("chat_option_provider"),
    )
    chat_parser.add_argument(
        "-v", "--verbose", action="store_true", help=_tr("chat_option_verbose")
    )
    chat_parser.add_argument(
        "-Q",
        "--quiet",
        action="store_true",
        help=_tr("chat_option_quiet"),
    )
    chat_parser.add_argument(
        "--resume",
        "-r",
        metavar="SESSION_ID",
        default=argparse.SUPPRESS,
        help=_tr("chat_option_resume"),
    )
    chat_parser.add_argument(
        "--continue",
        "-c",
        dest="continue_last",
        nargs="?",
        const=True,
        default=argparse.SUPPRESS,
        metavar="SESSION_NAME",
        help=_tr("option_continue"),
    )
    chat_parser.add_argument(
        "--worktree",
        "-w",
        action="store_true",
        default=argparse.SUPPRESS,
        help=_tr("chat_option_worktree"),
    )
    _inherited_flag(
        chat_parser,
        "--accept-hooks",
        action="store_true",
        default=argparse.SUPPRESS,
        help=_tr("chat_option_accept_hooks"),
    )
    chat_parser.add_argument(
        "--checkpoints",
        action="store_true",
        default=False,
        help=_tr("chat_option_checkpoints"),
    )
    chat_parser.add_argument(
        "--max-turns",
        type=int,
        default=None,
        metavar="N",
        help=_tr("chat_option_max_turns"),
    )
    _inherited_flag(
        chat_parser,
        "--yolo",
        action="store_true",
        default=argparse.SUPPRESS,
        help=_tr("option_yolo"),
    )
    _inherited_flag(
        chat_parser,
        "--pass-session-id",
        action="store_true",
        default=argparse.SUPPRESS,
        help=_tr("option_pass_session_id"),
    )
    _inherited_flag(
        chat_parser,
        "--ignore-user-config",
        action="store_true",
        default=argparse.SUPPRESS,
        help=_tr("chat_option_ignore_user_config"),
    )
    _inherited_flag(
        chat_parser,
        "--ignore-rules",
        action="store_true",
        default=argparse.SUPPRESS,
        help=_tr("chat_option_ignore_rules"),
    )
    chat_parser.add_argument(
        "--source",
        default=None,
        help=_tr("chat_option_source"),
    )
    _inherited_flag(
        chat_parser,
        "--tui",
        action="store_true",
        default=False,
        help=_tr("option_tui"),
    )
    _inherited_flag(
        chat_parser,
        "--dev",
        dest="tui_dev",
        action="store_true",
        default=False,
        help=_tr("option_dev"),
    )

    return parser, subparsers, chat_parser
