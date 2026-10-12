import argparse

import _bootstrap
import staging_deploy_runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('prepare', 'status'))
    parser.add_argument('--app-dir', required=True)
    parser.add_argument('--repo-dir')
    parser.add_argument('--commit', default='latest')
    parser.add_argument('--request-id', default='')
    parser.add_argument('--status', default='running')
    parser.add_argument('--step', default='start')
    parser.add_argument('--exit-code', type=int, default=0)
    parser.add_argument('--log-path')
    arguments = parser.parse_args()
    if arguments.action == 'prepare':
        if not arguments.repo_dir:
            parser.error('--repo-dir is required for prepare')
        staging_deploy_runtime.prepare_runtime(arguments.repo_dir, arguments.app_dir)
    else:
        staging_deploy_runtime.write_status(
            arguments.app_dir, arguments.commit, arguments.status, arguments.step,
            arguments.exit_code, arguments.request_id, arguments.log_path)


if __name__ == '__main__':
    main()
