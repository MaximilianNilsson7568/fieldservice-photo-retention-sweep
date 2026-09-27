"""Register the daily cleanup webhook with Infrai cron."""

import os

from fieldservice_cleanup import InfraiClient


def main() -> None:
    task_url = os.environ["CLEANUP_WEBHOOK_URL"]
    data = InfraiClient().create_cron(cron_expr="15 2 * * *", task=task_url)
    print(f"registered cleanup job: {data['job_id']}")


if __name__ == "__main__":
    main()
