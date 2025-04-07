import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import List, Dict, Tuple
import cmd2
from cmd2 import with_argparser, with_category
from argparse import ArgumentParser

class GitRepoManager(cmd2.Cmd):
    """Interactive tool to manage multiple Git repositories in parallel."""

    def __init__(self):
        super().__init__(
            allow_cli_args=False,
            persistent_history_file='~/.gitrepomanager_history',
            startup_script='~/.gitrepomanagerrc'
        )
        self.intro = "Git Repo Manager - Type 'help' for available commands"
        self.prompt = "git-mgr> "
        self.repos: Dict[str, str] = {}  # path -> branch mapping
        self.verbose = False
        self.threads = 4

    def _is_git_repo(self, path: str) -> bool:
        """Check if a directory is a Git repository."""
        git_dir = os.path.join(path, '.git')
        return os.path.isdir(git_dir)

    def _get_current_branch(self, repo_path: str) -> str:
        """Get the current branch of a Git repository."""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError:
            return "unknown"

    def _execute_git_command(self, repo_path: str, command: str) -> Tuple[str, str, bool]:
        """Execute a Git command in a repository and return the output."""
        try:
            result = subprocess.run(
                ['git'] + command.split(),
                cwd=repo_path,
                capture_output=True,
                text=True,
                check=True
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
    scan_parser.add_argument('-d', '--directory', help="Directory to scan (default: current directory)")

    @with_argparser(scan_parser)
    @with_category('discovery')
    def do_scan(self, args):
        """Scan for Git repositories in the specified directory or current directory."""
        scan_dir = args.directory or os.getcwd()
        
        if not os.path.isdir(scan_dir):
            self.perror(f"Directory not found: {scan_dir}")
            return
            
        self.poutput(f"Scanning for Git repositories in {scan_dir}...")
        
        self.repos = {}
        found_repos = 0
        
        for root, dirs, _ in os.walk(scan_dir):
            if '.git' in dirs:
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
    @with_category('discovery')
    def do_list(self, _=None):
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
    run_parser = ArgumentParser()
    run_parser.add_argument('command', nargs='+', help="Git command to execute")

    @with_argparser(run_parser)
    @with_category('execution')
    def do_git(self, args):
        """Execute a Git command in all repositories."""
        if not self.repos:
            self.perror("No repositories found. Use 'scan' to discover repositories.")
            return
            
        command = ' '.join(args.command)
        self.poutput(f"Executing 'git {command}' in {len(self.repos)} repositories...")
        
        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            results = list(executor.map(
                lambda repo: self._execute_git_command(repo, command),
                self.repos.keys()
            ))
        
        self._print_results(results)

    # Command: verbose
    verbose_parser = ArgumentParser()
    verbose_parser.add_argument('state', nargs='?', choices=['on', 'off'], help="Turn verbose output on or off")

    @with_argparser(verbose_parser)
    @with_category('configuration')
    def do_verbose(self, args):
        """Toggle verbose output (show all command results, not just errors)."""
        if args.state:
            self.verbose = (args.state == 'on')
        else:
            self.verbose = not self.verbose
            
        self.poutput(f"Verbose output is {'ON' if self.verbose else 'OFF'}")

    # Command: threads
    threads_parser = ArgumentParser()
    threads_parser.add_argument('num', type=int, help="Number of threads to use for parallel execution")

    @with_argparser(threads_parser)
    @with_category('configuration')
    def do_threads(self, args):
        """Set the number of threads to use for parallel execution."""
        if args.num < 1:
            self.perror("Number of threads must be at least 1")
            return
            
        self.threads = args.num
        self.poutput(f"Using {self.threads} threads for parallel execution")

if __name__ == '__main__':
    app = GitRepoManager()
    app.cmdloop()
