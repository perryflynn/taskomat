#!/usr/bin/python3

import os
import argparse
import datetime
import dateutil.parser
import yaml
import re
from pprint import pprint

from gitlabutils import api


class Housekeep:
    """ Housekeep functions """

    def __init__(self, gitlab_url, gitlab_token, gitlab_project):
        """ Initialize class """
        self.api = api.GitLabApi(gitlab_url, gitlab_token)
        self.project = gitlab_project
        self.milestones = None

    def get_issues(self):
        """ Get issues """
        for issue in self.api.get_project_issues(self.project, state='all', labels=''):
            yield issue

    def get_milestones(self):
        """ Get milestones """
        cfg_rgx = re.compile(r"^```yml[ \t]*$[\n\r]+^# TaskOMat config[ \t]*$[\n\r]+(.*?)^```[ \t]*$", re.M | re.S | re.I)
        for milestone in self.api.get_project_milestones(self.project, state='active'):
            match = cfg_rgx.search(milestone['description'])
            if match:
                # parse config and return
                try:
                    milestone['taskomat'] = yaml.load(match.group(1), Loader=yaml.FullLoader)
                    if 'label' in milestone['taskomat'].keys() and 'year' in milestone['taskomat'].keys():
                        yield milestone
                except:
                    pass

    def create_labelmilestone_config(self, label, year):
        """ Generate TaskOMat config text """
        cfgyml = yaml.dump({ 'label': label, 'year': year }, default_flow_style=False)
        return ":tea: This milestone is maintained by TaskOMat Housekeep:\n\n```yml\n# TaskOMat config\n" + cfgyml + "\n```\n"

    def ensure_assignee(self, issue, assignee_ids=[]):
        """ Assign someone when no one is assigned """
        do_assign = (
            'assignees' in issue.keys() and isinstance(issue['assignees'], list) and len(issue['assignees']) < 1
            and isinstance(assignee_ids, list) and len(assignee_ids) > 0
        )

        if do_assign:
            params = { 'assignee_ids': assignee_ids }
            updated = self.api.update_issue(self.project, issue['iid'], params)
            issue['assignees'] = updated['assignees']
            return True

        return False

    def ensure_milestone(self, issue, labels):
        """ Assign issue to a collection milestone """
        year = max([
            int((issue['updated_at'] if issue['updated_at'] else '0000')[0:4]),
            int((issue['due_date'] if issue['due_date'] else '0000')[0:4])
        ])

        if self.milestones is None:
            self.milestones = list(self.get_milestones())

        # assign a milestone
        if not issue['milestone']:
            issue_labels = list(filter(lambda x: x in labels, issue['labels']))
            if len(issue_labels) > 0:

                label_ms = list(filter(lambda x: x['taskomat']['label'] == issue_labels[0] and x['taskomat']['year'] == year, self.milestones))
                milestone_id = label_ms[0]['id'] if len(label_ms) > 0 else -1

                # create milestone if missing
                if milestone_id <= 0:
                    ms_due_start = str(year) + '-01-01'
                    ms_due_end = str(year) + '-12-31'
                    ms_name = issue_labels[0] + ' ' + str(year)
                    ms_description = self.create_labelmilestone_config(issue_labels[0], year)

                    new_milestone = self.api.post_project_milestone(self.project, ms_name, ms_description, ms_due_end, ms_due_start)
                    milestone_id = new_milestone['id']

                    self.milestones = list(self.get_milestones())

                # update issue
                params = { 'milestone_id': milestone_id }
                self.api.update_issue(self.project, issue['iid'], params)
                return True

        # unassign if the issue has not the required tag
        else:
            label_ms = list(filter(lambda x: x['id'] == issue['milestone']['id'], self.milestones))
            if len(label_ms) > 0 and label_ms[0]['taskomat']['label'] not in issue['labels']:

                # update issue
                params = { 'milestone_id': 0 }
                self.api.update_issue(self.project, issue['iid'], params)
                return True

        return False

    def ensure_locked(self, issue):
        """ Lock closed issue """
        if issue['state'] == 'closed' and (issue['discussion_locked'] is None or issue['discussion_locked'] != True):
            params = { 'discussion_locked': 'true' }
            updated = self.api.update_issue(self.project, issue['iid'], params)
            issue['discussion_locked'] = updated['discussion_locked']
            return True

        return False

    def ensure_confidential(self, issue):
        """ Set closed issue to confidential """
        if issue['state'] == 'closed' and (issue['confidential'] is None or issue['confidential'] != True):
            params = { 'confidential': 'true' }
            updated = self.api.update_issue(self.project, issue['iid'], params)
            issue['confidential'] = updated['confidential']
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
    parser.add_argument('--milestone-label', metavar='somelabel', action='append', help='Summarize issues with this label in a milestone')
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
                print("Set assignee for '" + issue['web_url'] + "'")

            # assign milestone by label
            if keep.ensure_milestone(issue, args.milestone_label):
                print("Set milestone for '" + issue['web_url'] + "'")

            # enforce locked discussion for closed issues
            if keep.ensure_locked(issue):
                print("Set locked for '" + issue['web_url'] + "'")

            # enforce confidential for closed issues
            if keep.ensure_confidential(issue):
                print("Set confidential for '" + issue['web_url'] + "'")

            # past due notification
            if keep.notify_past_due(issue):
                print("Send past due notice for '" + issue['web_url'] + "'")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
