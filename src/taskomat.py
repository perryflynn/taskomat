#!/usr/bin/python3

import os
import glob
import argparse
import yaml
import re
import datetime
import dateutil.parser
import dateutil.relativedelta
from pprint import pprint

from gitlabutils import api


LABEL_SELF = 'TaskOMat:Generated'


class TaskOMat:
    """ TaskOMat Business logic """

    def __init__(self, gitlab_url, gitlab_token, gitlab_project, collection_dir, updated_after):
        """ Initialize class """
        self.api = api.GitLabApi(gitlab_url, gitlab_token)
        self.project = gitlab_project
        self.label = LABEL_SELF
        self.dir = collection_dir
        self.updated_after = updated_after
        self.issues = None

    def get_collection_items(self):
        """ Open collection directory and parse all yml files """
        for filepath in glob.glob(self.dir + '/*.yml'):
            with open(filepath) as filehandle:
                temp = yaml.load(filehandle, Loader=yaml.FullLoader)
                if temp['taskomat']:
                    temp['taskomat']['key'] = os.path.splitext(os.path.basename(filepath))[0]
                    yield temp['taskomat']

    def get_issues(self):
        """ Get all issues """
        self.issues = []

        for issue in self.api.get_project_issues(self.project, state='all', labels=self.label, updated_after=self.updated_after):
            issue['taskomat'] = self.get_issue_config(issue['iid'])
            if issue['taskomat']:
                self.issues.append(issue)
                yield issue

    def get_issue_config(self, issue_iid):
        """ Find issue config """
        cfg_rgx = re.compile(r"^```yml[\t ]*\r?$\n^# TaskOMat config[\t ]*\r?$\n^(.*?)```[ \t]*\r?$", re.M | re.S | re.I)

        for note in self.api.get_issue_notes(self.project, issue_iid, sort='desc', order_by='updated_at'):
            match = cfg_rgx.search(note['body'])
            if match:
                # parse config and return
                try:
                    return { 'note_id': note['id'], 'config': yaml.load(match.group(1), Loader=yaml.FullLoader) }
                except:
                    pass

        # no config found
        return None

    def ensure_issues(self):
        """ Load all TaskOMat issues and store them """
        if (not self.issues) or len(self.issues) < 1:
            list(self.get_issues())

    def create_issueconfig(self, cfg):
        """ Generate TaskOMat config text """
        cfgyml = yaml.dump(cfg, default_flow_style=False)
        return ":tea: The following config is required for TaskOMat to work properly:\n\n```yml\n# TaskOMat config\n" + cfgyml + "\n```\n"

    def human_timedelta(self, delta):
        """ Make timedelta human readable """
        reldelta = dateutil.relativedelta.relativedelta(seconds=delta.total_seconds(), microseconds=delta.microseconds)
        attrs = ['years', 'months', 'days', 'hours', 'minutes', 'seconds']

        human_readable = lambda delta: ['%d %s' % (getattr(delta, attr), getattr(delta, attr) > 1 and attr or attr[:-1])
            for attr in attrs if getattr(delta, attr)]

        # just the first 2 elements
        deltalist = list(human_readable(reldelta))
        if len(deltalist) > 2:
            deltalist = deltalist[:2]

        # to string
        return ', '.join(deltalist)

    def post_or_update_config(self, issue, cfg):
        """ Create or update TaskOMat config """
        cfgtxt = self.create_issueconfig(cfg)

        if 'taskomat' in issue.keys() and 'note_id' in issue['taskomat'].keys():
            self.api.update_note(self.project, issue['iid'], issue['taskomat']['note_id'], cfgtxt)
            issue['taskomat']['config'] = cfg
        else:
            new_note = self.api.post_note(self.project, issue['iid'], cfgtxt)
            issue['taskomat'] = { 'note_id': new_note['id'], 'config': cfg }

    def create_issue(self, task):
        """ Create a issue from a task object """
        self.ensure_issues()
        now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

        # check if a open issue with the same key already exists
        existing = list(x for x in self.issues if x['state'] == 'opened' and x['taskomat']['config']['key'] == task['key'])

        if len(existing) > 0:
            # just create a ping-note
            issue = existing[0]

            # delete existing ping
            if 'ping_note' in issue['taskomat']['config'].keys():
                self.api.delete_note(self.project, issue['iid'], issue['taskomat']['config']['ping_note'])

            # create new ping
            pingtxt = '@' + (', @'.join(map(lambda x: x['username'], issue['assignees']))) + ' Ping...? :sleeping:'
            ping_note = self.api.post_note(self.project, issue['iid'], pingtxt)
            issue['taskomat']['config']['ping_note'] = ping_note['id']

            # update taskomat config
            if 'botcounter' not in issue['taskomat']['config'].keys():
                issue['taskomat']['config']['botcounter'] = 0

            issue['taskomat']['config']['botcounter'] += 1
            self.post_or_update_config(issue, issue['taskomat']['config'])

            return (True, [ 'result=updated_issue' ])

        else:
            # create a new issue
            if (self.label not in task['labels']):
                task['labels'].append(self.label)

            issue = self.api.post_issue(
                project=self.project,
                title=task['title'],
                body=task['description'],
                labels=(task['labels'] or []) if 'labels' in task.keys() else [],
                assignee_ids=(task['assignees'] or []) if 'assignees' in task.keys() else [],
                due_date=(datetime.datetime.now() + datetime.timedelta(days=task['due'])).strftime('%Y-%m-%d') if 'due' in task.keys() and task['due'] else ''
            )

            # create config as note
            self.post_or_update_config(issue, { 'key': task['key'], 'botcounter': 1 })

            pprint(self.get_project_issues(project=self.project, limit=2))

            # related items
            related_list = []
            related_items = list(x for x in self.issues if x['taskomat']['config']['key'] == task['key'])
            for related_item in related_items:
                # closed info
                closed_str = ''
                if related_item['closed_at']:
                    closed_date = dateutil.parser.isoparse(related_item['closed_at'])
                    closed_str = ' (closed ' + self.human_timedelta((now - closed_date)) + ' ago)'

                # related list item
                related_list.append('#' + str(related_item['iid']) + closed_str)

            # post related items as issue note
            if len(related_list) > 0:
                related_list_txt = "- " + ("\n- ".join(related_list))
                related_txt = ":clock2: :book: Related issues:\n\n" + related_list_txt
                self.api.post_note(self.project, issue['iid'], related_txt)

            return (True, [ 'result=created_issue' ])


def parse_args():
    """ Parse command line arguments """
    parser = argparse.ArgumentParser(description='TaskOMat for GitLab')
    parser.add_argument('--gitlab-url', metavar='https://git.example.com', type=str, required=True, help='GitLab private access token')
    parser.add_argument('--project', metavar='johndoe/todos', type=str, required=True, help='GitLab project')
    parser.add_argument('--collection-dir', metavar='~/.taskomat', type=str, required=True, help='Tasks collection folder')
    parser.add_argument('--max-updated-age', metavar='7776000', type=int, default=7776000, help='Process only issues which was updated in the last X seconds')
    return parser.parse_args()


def main():
    """ Main function """
    # command line args
    args = parse_args()

    # environment variables
    gitlab_token = os.environ.get('TASKOMAT_TOKEN')
    if not gitlab_token:
        raise ValueError('Environment variable \'TASKOMAT_TOKEN\' is not defined')

    # issue time range
    now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    updated_after = now - datetime.timedelta(seconds=args.max_updated_age)

    # initalize tasks
    omat = TaskOMat(
        gitlab_url=args.gitlab_url,
        gitlab_token=gitlab_token,
        gitlab_project=args.project,
        collection_dir=args.collection_dir,
        updated_after=updated_after
    )

    print(f"Collection dir: {args.collection_dir}")

    # create issues
    for task in omat.get_collection_items():
        result = omat.create_issue(task)
        print(f"Task item '{task['key']}': {', '.join(result[1])}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
