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


LABEL_OBSOLETE = 'Workflow:Obsolete'
LABEL_PUBLIC = 'Workflow:Public'
LABEL_WIP = 'Workflow:Work in Progress'
LABEL_HOLD = 'Workflow:On Hold'
LABEL_TASKOMAT_COUNTER = 'TaskOMat:Counter'


class Housekeep:
    """ Housekeep functions """

    def __init__(self, gitlab_url, gitlab_token, gitlab_project, updated_after, updated_before):
        """ Initialize class """
        self.api = api.GitLabApi(gitlab_url, gitlab_token)
        self.project = gitlab_project
        self.updated_after = updated_after
        self.updated_before = updated_before

    def get_issues(self, issue_iids=None):
        """ Get issues """
        issues = []

        if issue_iids and len(issue_iids) > 0:
            issues = self.api.get_project_issues(
                self.project, 
                state='all', 
                iids=issue_iids
            )

        else:
            issues = self.api.get_project_issues(
                self.project,
                state='all',
                labels='',
                updated_after=self.updated_after,
                updated_before=self.updated_before
            )

        for issue in issues:
            yield issue

    def ensure_obsolete(self, issue):
        """ Ensure obsolete issues are closed """
        if issue['state'] == 'opened' and LABEL_OBSOLETE in issue['labels']:
            params = { 'state_event': 'close' }
            updated = self.api.update_issue(self.project, issue['iid'], params)
            issue['state'] = updated['state']
            return (True, [ f"state={issue['state']}" ])

        return (False, [])

    def ensure_locked(self, issue):
        """ Lock closed issue """
        if issue['state'] == 'closed' and (issue['discussion_locked'] is None or issue['discussion_locked'] != True):
            params = { 'discussion_locked': 'true' }
            updated = self.api.update_issue(self.project, issue['iid'], params)
            issue['discussion_locked'] = updated['discussion_locked']
            return (True, [ f"discussion_locked={issue['discussion_locked']}" ])

        return (False, [])

    def ensure_confidential(self, issue):
        """ Set issue to confidential """
        
        is_closed = issue['state'] == 'closed'
        is_public = LABEL_PUBLIC in issue['labels']
        is_confidential = (issue['confidential'] is not None and issue['confidential'] == True)

        should_confidential = is_closed or not is_public
        
        if is_confidential != should_confidential:
            params = { 'confidential': 'true' if should_confidential else 'false' }
            updated = self.api.update_issue(self.project, issue['iid'], params)
            issue['confidential'] = updated['confidential']
            return (True, [ f"confidential={issue['confidential']}" ])

        return (False, [])

    def _parse_labelgroup(self, groupstr):
        """ Parse a single label group string """
        temp = groupstr.strip()
        
        isdefault = False
        if temp.endswith('*'):
            isdefault = True
        
        temp = temp.strip('*')
        return (temp, isdefault)

    def ensure_labels(self, issue, groups, categories, closedlabels):
        """ Set/Unset labels depending on issue state """

        labels_remove = []
        labels_add = []

        # remove labels when ticket closed
        is_closed = issue['state'] == 'closed'

        if is_closed and len(closedlabels) > 0:
            for closedlabel in closedlabels:
                if closedlabel in issue['labels']:
                    labels_remove.append(closedlabel)

        # get label events
        labelevents = []
        if len(groups) > 0:
            labelevents = list(sorted(filter(lambda x: x['action'] == 'add', self.api.get_issue_label_events(self.project, issue['iid'])), key=lambda x: x['created_at'], reverse=True))

        # group label rules
        for groupstr in groups:
            grouplabels = list(map(self._parse_labelgroup, groupstr.split(',')))
            defaultlabels = list(filter(lambda x: x[1], grouplabels))
            defaultlabel = defaultlabels[0][0] if len(defaultlabels) > 0 else None
            grouplabels = list(map(lambda x: x[0], grouplabels))

            # find used tags from the current group
            inuse = []
            for issuelabel in issue['labels']:
                if issuelabel in grouplabels:
                    inuse.append(issuelabel)
            
            # remove label if more than one from the current group
            if len(inuse) > 1:
                usedlabelevents = list(filter(lambda x: x['label']['name'] in inuse, labelevents))
                if len(usedlabelevents) > 0:
                    # remove label by event stream
                    labels_remove += list(filter(lambda x: x != usedlabelevents[0]['label']['name'], inuse))
                else:
                    # remove by list slice since event stream is empty
                    for toremove in inuse[:-1]:
                        labels_remove.append(toremove)
            
            elif len(inuse) <= 0 and defaultlabel is not None:
                labels_add.append(defaultlabel)

        # label category rules
        for categorystr in categories:
            categorylabels = list(map(lambda x: x[0], map(self._parse_labelgroup, categorystr.split(','))))

            if len(categorylabels) < 2:
                print(f"Invalid category label str: {categorystr}")
                continue

            expectedlabels = categorylabels[:-1]
            categorylabel = categorylabels[-1]

            # find used tags from the current group
            hascategory = categorylabel in issue['labels']
            hasexpected = False
            for issuelabel in issue['labels']:
                if issuelabel in expectedlabels:
                    hasexpected = True
            
            # add category if any label is assigned
            if hasexpected and not hascategory:
                labels_add.append(categorylabel)
            
            # remove category if no label is assigned
            elif not hasexpected and hascategory:
                labels_remove.append(categorylabel)

        # apply changes
        if len(labels_add) > 0 or len(labels_remove) > 0:
            params = { 
                'add_labels': ','.join(labels_add), 
                'remove_labels': ','.join(labels_remove)
            }
            
            if len(list(set(labels_remove) & set(labels_add))) > 0:
                raise Exception('One or more labels are on the add and remove list at the same time', params)

            updated = self.api.update_issue(self.project, issue['iid'], params)
            issue['labels'] = updated['labels']
            return (True, [ f"label_add={','.join(labels_add)}", f"label_remove={','.join(labels_remove)}" ])

        return (False, [])

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
            notinotes = list(filter(lambda x: x['body'].startswith(prefix), notes))

            # issue is past due
            if is_due:

                # create only a note if the last one is older than 24h
                createnew = True
                for notinote in notinotes:
                    update_date = dateutil.parser.isoparse(notinote['updated_at'])
                    if (now-update_date).total_seconds() >= 24 * 60 * 60:
                        self.api.delete_note(self.project, issue['iid'], notinote['id'])
                    else:
                        # at least one past due mention is not
                        # older than 24h, so create no new one
                        createnew = False

                # create a new past due notice
                if createnew:
                    mention = '@' + (', @'.join(map(lambda x: x['username'], issue['assignees'])))
                    txt = prefix + ' :alarm_clock: ' + mention + ' The issue is past due. :cold_sweat:'
                    self.api.post_note(self.project, issue['iid'], txt)
                    
                    return (True, [ 'past_due_note=created_new' ])

            # issue is not past due
            else:

                # delete existing notes
                if len(notinotes) > 0:
                    for notinote in notinotes:
                        self.api.delete_note(self.project, issue['iid'], notinote['id'])
                    
                    return (True, [ 'past_due_note=deleted' ])

        return (False, [])

    def _counter_monthgroup(self, x):
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

        if LABEL_TASKOMAT_COUNTER in issue['labels']:

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
                monthlyitems = list(map(self._counter_monthgroup, monthlyitemsiter))
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
                return (True, [ 'counter=updated' ])

            # create a new state note
            elif state_id is None and len(newstate_data['items']) > 0:
                self.api.post_note(self.project, issue['iid'], statebody)
                return (True, [ 'counter=created' ])

            # delete state config as the new state has no items
            elif state_id is not None and len(newstate_data['items']) <= 0:
                self.api.delete_note(self.project, issue['iid'], state_id)
                return (False, [])

        return (False, [])


def parse_args():
    """ Parse command line arguments """
    parser = argparse.ArgumentParser(description='TaskOMat Housekeeper for GitLab')

    # gitlab info
    parser.add_argument('--gitlab-url', metavar='https://git.example.com', type=str, required=True, help='GitLab private access token')
    parser.add_argument('--project', metavar='johndoe/todos', type=str, required=True, help='GitLab project')
    parser.add_argument('--assignee', metavar=42, type=int, default=0, help='Assign issue to this user id if unassigned')

    # filter issues
    parser.add_argument('--delay', metavar='900', type=int, default=900, help='Process only issues which wasn\'t updated X seconds')
    parser.add_argument('--max-updated-age', metavar='7776000', type=int, default=7776000, help='Process only issues which was updated in the last X seconds')
    parser.add_argument('--issue-iid', metavar='42', type=int, default=0, help='Filter for one specific issue iid')
    parser.add_argument('--issue-iids', metavar='40,41,42', type=str, default='', help='Filter for a comma separated list of issue iid')

    # label features
    parser.add_argument('--label-group', metavar='somelabel', action='append', help='Group label and assign default label to issues')
    parser.add_argument('--label-category', metavar='somelabel,someotherlabel', action='append', help='Add the last label in the list if one of the others are assigned to the issue')
    parser.add_argument('--closed-remove-labels', metavar='somelabel', action='append', help='Remove labels when issue is closed')

    # issue features
    parser.add_argument('--close-obsolete', action='store_true', help='Close issues labled as obsolete', default=False)
    parser.add_argument('--lock-closed', action='store_true', help='Lock notes on closed issues', default=False)
    parser.add_argument('--set-confidential', action='store_true', help='Set all issues to confidential is no public label present', default=False)
    parser.add_argument('--notify-due', action='store_true', help='Post a note when issue is due', default=False)

    # note features
    parser.add_argument('--counters', action='store_true', help='Process counters', default=False)

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
    issue_iids = []

    if args.issue_iid and args.issue_iid > 0:
        issue_iids.append(args.issue_iid)

    if args.issue_iids:
        temp = args.issue_iids
        for temp_iid in map(lambda x: x.strip(), temp.split(',')):
            if temp_iid:
                issue_iids.append(int(temp_iid))

    if len(issue_iids) > 0:
        print(f"Issue IIDs: {', '.join(map(str, issue_iids))}")

    ctr_issues = 0
    ctr_processed = 0
    
    for issue in keep.get_issues(issue_iids if len(issue_iids) > 0 else None):
        ctr_issues += 1
        messages = []

        # enforce closed state for obsolete issues
        if args.close_obsolete:
            messages += keep.ensure_obsolete(issue)[1]

        # enforce locked discussion for closed issues
        if args.lock_closed:
            messages += keep.ensure_locked(issue)[1]

        # enforce confidential for closed issues
        if args.set_confidential:
            messages += keep.ensure_confidential(issue)[1]

        # enforce certain label rules based on the state of the issue
        labelgroups = args.label_group if args.label_group and len(args.label_group) > 0 else []
        labelcategories = args.label_category if args.label_category and len(args.label_category) > 0 else []
        closedlabels = args.closed_remove_labels if args.closed_remove_labels and len(args.closed_remove_labels) > 0 else []
        
        messages += keep.ensure_labels(issue, labelgroups, labelcategories, closedlabels)[1]

        # past due notification
        if args.notify_due:
            messages += keep.notify_past_due(issue)[1]

        # process counter
        if args.counters:
            messages += keep.process_counters(issue)[1]

        # result
        if len(messages) > 0:
            ctr_processed += 1
            print(f"Touched issue #{issue['iid']}: {', '.join(messages)}")

    print(f"Processed {ctr_processed} of {ctr_issues} issues")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
