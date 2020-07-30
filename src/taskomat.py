#!/usr/bin/python3

import os
import glob
import argparse
import yaml
import re
import datetime

from gitlabutils import api


class TaskOMat:
    """ TaskOMat Business logic """

    def __init__(self, gitlab_url, gitlab_token, gitlab_project, collection_dir):
        """ Initialize class """
        self.api = api.GitLabApi(gitlab_url, gitlab_token)
        self.project = gitlab_project
        self.label = 'TaskOMat'
        self.dir = collection_dir
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

        for issue in self.api.get_project_issues(self.project, state='opened', labels=self.label):
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

        # check if a open issue with the same key already exists
        existing = list(x for x in self.issues if x['taskomat']['config']['key'] == task['key'])

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


def parse_args():
    """ Parse command line arguments """
    parser = argparse.ArgumentParser(description='TaskOMat for GitLab')
    parser.add_argument('--gitlab-url', metavar='https://git.example.com', type=str, required=True, help='GitLab private access token')
    parser.add_argument('--project', metavar='johndoe/todos', type=str, required=True, help='GitLab project')
    parser.add_argument('--collection-dir', metavar='~/.taskomat', type=str, required=True, help='Tasks collection folder')
    return parser.parse_args()


def main():
    """ Main function """
    # command line args
    args = parse_args()

    # environment variables
    gitlab_token = os.environ.get('TASKOMAT_TOKEN')
    if not gitlab_token:
        raise ValueError('Environment variable \'TASKOMAT_TOKEN\' is not defined')

    # initalize tasks
    omat = TaskOMat(
        gitlab_url=args.gitlab_url,
        gitlab_token=gitlab_token,
        gitlab_project=args.project,
        collection_dir=args.collection_dir
    )

    # create issues
    for task in omat.get_collection_items():
        omat.create_issue(task)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
