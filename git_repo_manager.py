"""Git Repo Manager - A command-line tool to manage multiple Git repositories
in parallel.

This tool allows you to scan for Git repositories in a directory, list them,
execute Git commands in all repositories, and manage their branches.
It uses Python's cmd2 library for a user-friendly command-line interface
"""

import os
import shlex
import subprocess
from argparse import ArgumentParser
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Tuple

import cmd2
from cmd2 import with_argparser, with_category


class GitRepoManager(cmd2.Cmd):
    """Interactive tool to manage multiple Git repositories in parallel."""

    def __init__(self):
        super().__init__(
            allow_cli_args=False,
            persistent_history_file="~/.gitrepomanager_history",
            # startup_script="~/.gitrepomanagerrc",
        )
        self.intro = "Git Repo Manager - Type 'help' for available commands"
        self.prompt = "git-mgr> "
        self.repos: Dict[str, str] = {}  # path -> branch mapping
        self.verbose = False
        self.threads = 4

    def _is_git_repo(self, path: str) -> bool:
        """Check if a directory is a Git repository."""
        git_dir = os.path.join(path, ".git")
        return os.path.isdir(git_dir)

    def _get_current_branch(self, repo_path: str) -> str:
        """Get the current branch of a Git repository."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return "unknown"

    def _execute_git_command(
        self, repo_path: str, command: str
    ) -> Tuple[str, str, bool]:
        """Execute a Git command in a repository and return the output."""
        try:
            result = subprocess.run(
                ["git"] + shlex.split(command),
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
            )
            return (repo_path, result.stdout.strip(), True)
        except subprocess.CalledProcessError as e:
            return (repo_path, f"Error in {repo_path}:\n{e.stderr.strip()}", False)

    def _print_results(self, results: List[Tuple[str, str, bool]]) -> None:
        """Print results based on verbose setting."""
        for repo_path, output, success in results:
            if not success or self.verbose:
                self.poutput(f"\n=== {os.path.basename(repo_path)} ===")
                self.poutput(output)

    # Command: scan
    scan_parser = ArgumentParser()
    scan_parser.add_argument(
        "-d", "--directory", help="Directory to scan (default: current directory)"
    )

    @with_argparser(scan_parser)
    @with_category("discovery")
    def do_scan(self, args=""):
        """Scan for Git repositories in the specified directory or current
        directory.
        """
        scan_dir = args.directory or os.getcwd()

        if not os.path.isdir(scan_dir):
            self.perror(f"Directory not found: {scan_dir}")
            return

        self.poutput(f"Scanning for Git repositories in {scan_dir}...")

        self.repos = {}
        found_repos = 0

        for root, dirs, _ in os.walk(scan_dir):
            if ".git" in dirs:
                repo_path = os.path.abspath(root)
                branch = self._get_current_branch(repo_path)
                self.repos[repo_path] = branch
                found_repos += 1
                # Don't walk into subdirectories of a Git repo
                dirs[:] = []

        self.poutput(f"Found {found_repos} Git repositories.")
        if found_repos > 0:
            self.do_list()

    # Command: list
    @with_category("discovery")
    def do_list(self, _=""):
        """List all discovered Git repositories and their current branches."""
        if not self.repos:
            self.poutput("No repositories found. Use 'scan' to discover repositories.")
            return

        max_path_len = max(len(os.path.basename(path)) for path in self.repos.keys())

        self.poutput("\nDiscovered Git repositories:")
        self.poutput(f"{'Repository':<{max_path_len}}  Branch")
        self.poutput("-" * (max_path_len + 20))

        for path, branch in sorted(self.repos.items()):
            self.poutput(f"{os.path.basename(path):<{max_path_len}}  {branch}")

    # Command: git
    @with_category("execution")
    def do_git(self, statement="git help"):
        """Execute a Git command in all repositories."""
        if not self.repos:
            self.perror("No repositories found. Use 'scan' to discover repositories.")
            return

        if isinstance(statement, cmd2.Statement):
            command = statement.raw.split(" ", 1)[1]
        else:
            command = statement.split(" ", 1)[1]

        self.poutput(f"Executing 'git {command}' in {len(self.repos)} repositories...")

        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            results = list(
                executor.map(
                    lambda repo: self._execute_git_command(repo, command),
                    self.repos.keys(),
                )
            )

        self._print_results(results)

    def default(self, statement):
        """If unknown command, send it as if it started with git."""

        # save entered item to history:
        self.history.append(statement)

        self.do_git("git " + statement.raw)

    # Command: verbose
    verbose_parser = ArgumentParser()
    verbose_parser.add_argument(
        "state", nargs="?", choices=["on", "off"], help="Turn verbose output on or off"
    )

    @with_argparser(verbose_parser)
    @with_category("configuration")
    def do_verbose(self, args=""):
        """Toggle verbose output (show all command results, not just errors)."""
        if args.state:
            self.verbose = args.state == "on"
        else:
            self.verbose = not self.verbose

        self.poutput(f"Verbose output is {'ON' if self.verbose else 'OFF'}")

    # Command: threads
    threads_parser = ArgumentParser()
    threads_parser.add_argument(
        "num",
        type=int,
        help="Number of threads to use for parallel execution",
    )

    @with_argparser(threads_parser)
    @with_category("configuration")
    def do_threads(self, args):
        """Set the number of threads to use for parallel execution."""
        if args.num < 1:
            self.perror("Number of threads must be at least 1")
            return

        self.threads = args.num
        self.poutput(f"Using {self.threads} threads for parallel execution")

    def do_exit(self, _=""):
        """Exit this application."""
        return self.do_quit("")

    def _get_default_branch(self, repo_path: str) -> str:
        """Determine the default branch for a repository."""
        try:
            # First try to get the default branch from remote
            result = subprocess.run(
                ["git", "remote", "show", "origin"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
            )
            # Parse the output to find the default branch
            for line in result.stdout.splitlines():
                if "HEAD branch" in line:
                    return line.split(":")[-1].strip()

            # Fallback to checking for common branch names
            branches = subprocess.run(
                ["git", "branch", "-a"],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True,
            ).stdout

            if "main" in branches:
                return "main"
            if "master" in branches:
                return "master"

            return "unknown"
        except subprocess.CalledProcessError:
            return "unknown"

    # Command: branch_switch_default
    @with_category("execution")
    def do_branch_switch_default(self, _=""):
        """Switch all repositories to their default branch (main/master)."""
        if not self.repos:
            self.perror("No repositories found. Use 'scan' to discover repositories.")
            return

        self.poutput(
            f"Switching to default branches in {len(self.repos)} repositories..."
        )

        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            # First get default branches for all repos
            default_branches = list(
                executor.map(
                    lambda repo: (repo, self._get_default_branch(repo)),
                    self.repos.keys(),
                )
            )

            # Then switch to those branches
            results = list(
                executor.map(
                    lambda repo_branch: self._execute_git_command(
                        repo_branch[0], f"checkout {repo_branch[1]}"
                    ),
                    default_branches,
                )
            )

        self._print_results(results)
        # Update our branch cache
        for repo_path in self.repos:
            self.repos[repo_path] = self._get_current_branch(repo_path)


if __name__ == "__main__":
    app = GitRepoManager()
    app.cmdloop()
