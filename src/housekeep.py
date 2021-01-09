#!/usr/bin/python3

import os
import argparse
import datetime
import dateutil.parser
import yaml
import re
import itertools
import urllib.parse

from gitlabutils import api


class Housekeep:
    """ Housekeep functions """

    def __init__(self, gitlab_url, gitlab_token, gitlab_project, updated_after, updated_before):
        """ Initialize class """
        self.api = api.GitLabApi(gitlab_url, gitlab_token)
        self.project = gitlab_project
        self.milestones = None
        self.updated_after = updated_after
        self.updated_before = updated_before

    def get_issues(self):
        """ Get issues """
        issues = self.api.get_project_issues(
            self.project,
            state='all',
            labels='',
            updated_after=self.updated_after,
            updated_before=self.updated_before
        )

        for issue in issues:
            yield issue

    def get_milestones(self):
        """ Get milestones """
        cfg_rgx = re.compile(r"^```yml[\t ]*\r?$\n^# TaskOMat config[\t ]*\r?$\n^(.*?)```[ \t]*\r?$", re.M | re.S | re.I)
        for milestone in self.api.get_project_milestones(self.project, state='active'):
            match = cfg_rgx.search(str(milestone['description']))
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
                updated = self.api.update_issue(self.project, issue['iid'], params)
                issue['milestone'] = updated['milestone']
                return True

        # unassign if the issue has not the required tag
        else:
            label_ms = list(filter(lambda x: x['id'] == issue['milestone']['id'], self.milestones))
            if len(label_ms) > 0 and label_ms[0]['taskomat']['label'] not in issue['labels']:

                # update issue
                params = { 'milestone_id': 0 }
                updated = self.api.update_issue(self.project, issue['iid'], params)
                issue['milestone'] = updated['milestone']
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

        if issue['state'] == 'opened':

            # check due state
            now = datetime.datetime.now().replace(tzinfo=datetime.timezone.utc)
            is_due = False
            if  issue['due_date']:
                due_date = datetime.datetime.strptime(issue['due_date'], '%Y-%m-%d').replace(tzinfo=datetime.timezone.utc)
                is_due = (now-due_date).total_seconds() >= 24 * 60 * 60

            # find existing past due notes
            notes = list(self.api.get_issue_notes(self.project, issue['iid']))
            notinotes = filter(lambda x: x['body'].startswith(prefix), notes)

            # issue is past due
            if is_due:

                # create only a note if the last one is older than 24h
                for notinote in notinotes:
                    update_date = dateutil.parser.isoparse(notinote['updated_at'])
                    if (now-update_date).total_seconds() >= 24 * 60 * 60:
                        self.api.delete_note(self.project, issue['iid'], notinote['id'])
                    else:
                        # at least one past due mention is not
                        # older than 24h, so create no new one
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

    def counter_monthgroup(self, x):
        """ Helper function used when creating monthly summary for counters """

        items = list(x[1])
        return {
            'date': x[0],
            'count': len(items),
            'amount': sum(item['amount'] for item in items),
        }

    def process_counters(self, issue):
        """ Process counting requests """

        ctr_rgx = re.compile(r"^\!count\s+(?P<amount>[0-9]+(?:\.[0-9]+)?)(?:\s+(?P<timestamp>[0-9]{4}-[0-9]{2}-[0-9]{2}))?\s*$", re.M | re.I)
        unit_rgx = re.compile(r"^\!countunit\s+(?P<unit>[^\s]+)\s*$", re.M | re.I)
        goal_rgx = re.compile(r"^\!countgoal\s+(?P<goal>[0-9]+(?:\.[0-9]+)?)\s*$", re.M | re.I)

        state_rgx = re.compile(r"^```yml[\t ]*\r?$\n^# TaskOMat counter state[\t ]*\r?$\n^(.*?)```[ \t]*\r?$", re.M | re.S | re.I)
        state_id = None
        state_data = None
        newstate_data = { 'last_updated': None, 'unit': None, 'goal': None, 'items': [] }

        summary_prefix = '`TaskOMat:countersummary`'
        summary_id = None

        if 'Counter' in issue['labels']:

            # iterate all notes
            for note in self.api.get_issue_notes(self.project, issue['iid']):
                note_created = dateutil.parser.isoparse(note['created_at'])
                note_updated = dateutil.parser.isoparse(note['updated_at'])

                # remember ID for the summary note
                if summary_id is None and note['body'].startswith(summary_prefix):
                    summary_id = note['id']

                # find and load counter state
                match = state_rgx.search(str(note['body']))
                if match:
                    try:
                        state_data = yaml.load(match.group(1), Loader=yaml.FullLoader)
                        state_id = note['id']
                    except:
                        pass

                # search for counter requests and add them to state data
                else:
                    ismatch = False
                    for _, match in enumerate(ctr_rgx.finditer(note['body']), 1):
                        ismatch = True
                        date = match.group('timestamp') if match.group('timestamp') else note_created.strftime('%Y-%m-%d')
                        amount = float(match.group('amount'))
                        newstate_data['items'].append({ 'date': date, 'amount': amount, 'note_id': note['id'] })

                    for _, match in enumerate(unit_rgx.finditer(note['body']), 1):
                        ismatch = True
                        newstate_data['unit'] = match.group('unit')

                    for _, match in enumerate(goal_rgx.finditer(note['body']), 1):
                        ismatch = True
                        newstate_data['goal'] = float(match.group('goal'))

                    if ismatch:
                        if newstate_data['last_updated'] is None or newstate_data['last_updated'] < note_updated:
                            newstate_data['last_updated'] = note_updated

            # sort items by date and note_id
            newstate_data['items'] = list(sorted(newstate_data['items'], key=lambda x: x['date']+'-'+str(x['note_id'])))

            # create state
            stateyml = yaml.dump(newstate_data, default_flow_style=None)
            statebody = ":tea: The following config is required for TaskOMat counter to work properly:\n\n```yml\n# TaskOMat counter state\n" + stateyml + "\n```\n"

            # create/update summary
            if (summary_id is None or state_data['last_updated'] < newstate_data['last_updated']) and len(newstate_data['items']) > 0:

                unit = ' '+newstate_data['unit'] if newstate_data['unit'] else ''
                summaryrows = [
                    summary_prefix+' :tea: Here is the TaskOMat counter summary:',
                ]

                # monthly summary
                groupkeyfunc = lambda x: x['date'][0:7]
                monthlyitemsiter = itertools.groupby(sorted(newstate_data['items'], key=groupkeyfunc), groupkeyfunc)
                monthlyitems = list(map(self.counter_monthgroup, monthlyitemsiter))
                largestmonth = max(monthlyitems, key=lambda x: x['amount'])['date']
                mostmonth = max(monthlyitems, key=lambda x: x['count'])['date']

                # other stats
                total = sum(item['amount'] for item in newstate_data['items'])
                totalcount = len(newstate_data['items'])
                itemstimesorted = sorted(newstate_data['items'], key=lambda x: x['date'])
                minamount = min(item['amount'] for item in newstate_data['items'])
                maxamount = max(item['amount'] for item in newstate_data['items'])

                # generate some general stats
                summaryrows.append('')
                summaryrows.append('**Processed:** '+str(round(totalcount, 2))+' items  ')
                summaryrows.append('**Time range:** '+itemstimesorted[0]['date']+' - '+itemstimesorted[-1]['date']+'  ')
                summaryrows.append('**Smallest Amount:** '+str(round(minamount, 2))+unit+'  ')
                summaryrows.append('**Largest Amount:** '+str(round(maxamount, 2))+unit)

                # generate goal stats
                if newstate_data['goal'] is not None:
                    goal = newstate_data['goal']
                    percentage = 100 * total / goal
                    suffix = f"% ({int(round(total))}{unit.strip()} of {int(round(goal))}{unit.strip()})"
                    summaryrows.append('')
                    summaryrows.append('**Goal:**  ')
                    summaryrows.append('![grand progress](https://progress-bar.dev/'+str(int(round(percentage)))+'/?scale=100&width=260&color=0072ef&suffix='+urllib.parse.quote(suffix, safe='')+')')

                # generate month table
                summaryrows.append('')
                summaryrows.append('| Month | Items | Amount |')
                summaryrows.append('|---|---|---|')
                for monthitem in monthlyitems:
                    maxyay = ' :tada:' if largestmonth == monthitem['date'] else ''
                    mostyay = ' :tada:' if mostmonth == monthitem['date'] else ''
                    summaryrows.append('| '+monthitem['date']+' | '+str(monthitem['count'])+mostyay+' | '+str(round(monthitem['amount'], 2))+unit+maxyay+' |')
                summaryrows.append('')

                # grand total
                lastamount = ' (+'+str(round(newstate_data['items'][-1]['amount'], 2))+unit+' last)' if len(newstate_data['items']) > 0 else ''
                summaryrows.append('**Total:** '+str(round(total, 2))+unit+lastamount)
                summaryrows.append('')

                # post summary
                summarybody = '\n'.join(summaryrows)

                if summary_id is None:
                    self.api.post_note(self.project, issue['iid'], summarybody)
                else:
                    self.api.update_note(self.project, issue['iid'], summary_id, summarybody)

            # delete summary if no items in state
            elif summary_id is not None and len(newstate_data['items']) < 1:
                self.api.delete_note(self.project, issue['iid'], summary_id)

            # update existing state note
            if state_id is not None and state_data['last_updated'] < newstate_data['last_updated'] and len(newstate_data['items']) > 0:
                self.api.update_note(self.project, issue['iid'], state_id, statebody)
                return True

            # create a new state note
            elif state_id is None and len(newstate_data['items']) > 0:
                self.api.post_note(self.project, issue['iid'], statebody)
                return True

            # delete state config as the new state has no items
            elif state_id is not None and len(newstate_data['items']) <= 0:
                self.api.delete_note(self.project, issue['iid'], state_id)
                return False


def parse_args():
    """ Parse command line arguments """
    parser = argparse.ArgumentParser(description='TaskOMat Housekeeper for GitLab')

    parser.add_argument('--gitlab-url', metavar='https://git.example.com', type=str, required=True, help='GitLab private access token')
    parser.add_argument('--project', metavar='johndoe/todos', type=str, required=True, help='GitLab project')
    parser.add_argument('--assignee', metavar=42, type=int, default=0, help='Assign issue to this user id if unassigned')
    parser.add_argument('--milestone-label', metavar='somelabel', action='append', help='Summarize issues with this label in a milestone')
    parser.add_argument('--delay', metavar='900', type=int, default=900, help='Process only issues which wasn\'t updated X seconds')
    parser.add_argument('--max-updated-age', metavar='7776000', type=int, default=7776000, help='Process only issues which was updated in the last X seconds')

    return parser.parse_args()


def main():
    """ Main function """
    # command line args
    args = parse_args()

    # args from environment variables
    gitlab_token = os.environ.get('TASKOMAT_TOKEN')
    if not gitlab_token:
        raise ValueError('Environment variable \'TASKOMAT_TOKEN\' is not defined')

    # issue time range
    now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)
    updated_after = now - datetime.timedelta(seconds=args.max_updated_age)
    updated_before = now - datetime.timedelta(seconds=args.delay)

    # initialize tasks
    keep = Housekeep(
        gitlab_url=args.gitlab_url,
        gitlab_token=gitlab_token,
        gitlab_project=args.project,
        updated_after=updated_after,
        updated_before=updated_before
    )

    # execute tasks for each issue
    for issue in keep.get_issues():

        # enforce assignee if none set
        if args.assignee > 0 and keep.ensure_assignee(issue, [ args.assignee ]):
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

        if keep.process_counters(issue):
            print("Process counters for '" + issue['web_url'] + "'")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
