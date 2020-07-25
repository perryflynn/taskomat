#!/usr/bin/python3

import os
import argparse
import datetime
import dateutil.parser
from pprint import pprint

from gitlabutils import api


class Housekeep:
    """ Housekeep functions """

    def __init__(self, gitlab_url, gitlab_token, gitlab_project):
        """ Initialize class """
        self.api = api.GitLabApi(gitlab_url, gitlab_token)
        self.project = gitlab_project

    def get_issues(self):
        """ Get issues """
        for issue in self.api.get_project_issues(self.project, state='all', labels=''):
            yield issue

    def ensure_assignee(self, issue, assignee_ids=[]):
        """ Assign someone when no one is assigned """
        do_assign = (
            'assignees' in issue.keys() and isinstance(issue['assignees'], list) and len(issue['assignees']) < 1
            and isinstance(assignee_ids, list) and len(assignee_ids) > 0
        )

        if do_assign:
            params = { 'assignee_ids': assignee_ids }
            self.api.update_issue(self.project, issue['iid'], params)
            return True

        return False

    def ensure_locked(self, issue):
        """ Lock closed issue """
        if issue['state'] == 'closed' and issue['discussion_locked'] == False:
            params = { 'discussion_locked': 'true' }
            self.api.update_issue(self.project, issue['iid'], params)
            return True

        return False

    def ensure_confidential(self, issue):
        """ Set closed issue to confidential """
        if issue['state'] == 'closed' and issue['confidential'] == False:
            params = { 'confidential': 'true' }
            self.api.update_issue(self.project, issue['iid'], params)
            return True

        return False

    def notify_past_due(self, issue):
        """ Send mention when the issue is past due """
        prefix = '`housekeep:pastdueinfo`'

        if issue['state'] == 'opened' and issue['due_date']:
            now = datetime.datetime.now().replace(tzinfo=datetime.timezone.utc)
            due_date = datetime.datetime.strptime(issue['due_date'], '%Y-%m-%d').replace(tzinfo=datetime.timezone.utc)

            # find existing past due notes
            notes = list(self.api.get_issue_notes(self.project, issue['iid']))
            notinotes = filter(lambda x: x['body'].startswith(prefix), notes)

            # issue is past due
            if (now-due_date).total_seconds() >= 24 * 60 * 60:

                # create only a note if the last one is older that 24h
                for notinote in notinotes:
                    update_date = dateutil.parser.isoparse(notinote['updated_at'])
                    if (now-update_date).total_seconds() >= 24 * 60 * 60:
                        self.api.delete_note(self.project, issue['iid'], notinote['id'])
                    else:
                        return True

                # create a new past due notice
                mention = '@' + (', @'.join(map(lambda x: x['username'], issue['assignees'])))
                txt = prefix + ' :alarm_clock: ' + mention + ' The issue is past due. :cold_sweat:'
                self.api.post_note(self.project, issue['iid'], txt)

            # issue is not past due
            else:

                # delete existing notes
                for notinote in notinotes:
                    self.api.delete_note(self.project, issue['iid'], notinote['id'])

        return False


def parse_args():
    """ Parse command line arguments """
    parser = argparse.ArgumentParser(description='TaskOMat for GitLab')
    parser.add_argument('--gitlab-url', metavar='https://git.example.com', type=str, help='GitLab private access token')
    parser.add_argument('--project', metavar='johndoe/todos', type=str, help='GitLab project')
    parser.add_argument('--assignee', metavar=42, type=int, help='Fallback assignee')
    return parser.parse_args()


def main():
    """ Main function """
    args = parse_args()
    gitlab_token = os.environ.get('TASKOMAT_TOKEN')
    keep = Housekeep(gitlab_url=args.gitlab_url, gitlab_token=gitlab_token, gitlab_project=args.project)

    now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

    for issue in keep.get_issues():
        # only handle issues which are unmodified some time
        last_update = dateutil.parser.isoparse(issue['updated_at'])
        if (now-last_update).total_seconds() >= (15 * 60):

            # enforce assignee if none set
            if keep.ensure_assignee(issue, [ args.assignee ]):
                print("Set assignee to '" + issue['web_url'] + "'")

            # enforce locked discussion for closed issues
            if keep.ensure_locked(issue):
                print("Set locked to '" + issue['web_url'] + "'")

            # enforce confidential for closed issues
            if keep.ensure_confidential(issue):
                print("Set confidential to '" + issue['web_url'] + "'")

        keep.notify_past_due(issue)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
