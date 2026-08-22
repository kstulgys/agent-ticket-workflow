"""Run git with the credential in the environment, never in argv."""
import os
import subprocess
import sys

from . import http, secrets

# One token variable for each host kind. A single fallback name cannot serve
# both kinds. With one name, an Azure Repos host that names no auth_env sends a
# GitHub token to an Azure server, which is the cross-provider mix-up to stop.
TOKEN_ENV = {"azure-repos": "AZDO_PAT", "github": "GH_TOKEN"}
GITHUB_URL = "https://github.com/"
# The user half of the credential for a github host. Azure Repos takes an empty
# user beside a PAT, and github over https refuses one. A host block that names
# no user would build Basic base64(":token"), and every push would fail with a
# credential that looks right in the config.
GITHUB_USER = "x-access-token"
# git answers 128 for a fatal error. run promises an int, so a spawn that fails
# answers with this code, not with a traceback.
FATAL = 128


def env_for(profile, values):
    host = profile.get("host") or {}
    kind = host.get("kind")
    if kind not in TOKEN_ENV:
        raise ValueError(
            f"profile {profile.get('slug')} has host.kind {kind!r}. gitcmd "
            f"serves {' and '.join(sorted(TOKEN_ENV))}. "
            "Fix host.kind in config.json.")
    # Read the config before the secret. A profile error then names the setting
    # to fix, and no token is in memory when it does.
    key = f"http.{_base_url(profile, kind)}.extraheader"
    auth = host.get("auth_env") or {}
    token = secrets.get(auth.get("token") or TOKEN_ENV[kind], values)
    user = values.get(auth["user"], "") if auth.get("user") else ""
    if not user and kind == "github":
        user = GITHUB_USER
    # Start from the parent environment. git needs HOME to read its own config,
    # and PATH to find its helper programs.
    env = dict(os.environ)
    # git reads http.<url>.extraheader from these three names, so the token
    # stays out of argv, where ps and a shell history file can read it. A token
    # in a remote url is worse, because .git/config holds it after the command
    # ends. GIT_TERMINAL_PROMPT=0 turns a password prompt into an error, so a
    # wrong credential fails now instead of blocking the run.
    env.update({"GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": key,
                "GIT_CONFIG_VALUE_0": "AUTHORIZATION: " + http.basic(user, token),
                "GIT_TERMINAL_PROMPT": "0"})
    return env


def _base_url(profile, kind):
    """The url this credential belongs to. The caller checks the kind first.

    git sends an http.<url>.extraheader value with a request under that url
    only. A bare http.extraheader value goes to every host in the command, so a
    submodule fetch during a clone hands our token to the host that submodule
    lives on. Azure Pipelines scopes its own header for this reason.
    """
    if kind == "github":
        return GITHUB_URL
    org = (profile.get("tracker") or {}).get("org")
    if not org:
        raise ValueError(
            f"profile {profile.get('slug')} has an {kind} host and no "
            "tracker.org. gitcmd scopes the credential to that url, and an "
            "unscoped credential goes to every host. Add tracker.org to "
            "config.json.")
    return org


def _default_runner(argv, cwd, env):
    try:
        return subprocess.call(argv, cwd=cwd, env=env)
    except OSError as error:
        # A local_path that is not there, or a git binary that is not on PATH,
        # raises here. run promises an int, so answer with a code and print one
        # line. scrub runs because the error quotes a path we passed in.
        sys.stderr.write(secrets.scrub(f"cannot run git: {error}") + "\n")
        return FATAL


def run(profile, values, args, cwd=None, runner=None):
    host = profile.get("host") or {}
    identity = host.get("identity") or {}
    argv = ["git"]
    if identity.get("name"):
        argv += ["-c", f"user.name={identity['name']}"]
    if identity.get("email"):
        argv += ["-c", f"user.email={identity['email']}"]
    argv += list(args)
    target = cwd or os.path.expanduser(host.get("local_path") or ".")
    return (runner or _default_runner)(argv, target, env_for(profile, values))
