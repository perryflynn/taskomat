import requests
import urllib.parse

class GitLabApi:
    """ GitLab API functions """

    def __init__(self, gitlab_url, gitlab_token):
        """ Initialize class """
        self.url = gitlab_url
        self.token = gitlab_token

    def get_project_milestones(self, project, state='active'):
        """ Get all milestones """
        self.issues = []
        item_buffer = []
        item_count = 100
        page_count = 1

        url = self.url + '/api/v4/projects/' + urllib.parse.quote(project, safe='') + '/milestones'
        headers = { 'PRIVATE-TOKEN': self.token }
        params = { 'page': 0, 'per_page': item_count, 'state': state }

        while True:
            # fetch a page of issues
            params['page'] = page_count
            r = requests.get(url, params=params, headers=headers)
            item_buffer = r.json()

            for item in item_buffer:
                yield item

            # next page until non-full buffer
            page_count += 1
            if len(item_buffer) < item_count:
                break

        return

    def post_project_milestone(self, project, title, description='', due_date='', start_date=''):
        """ Create a new milestone """
        issue_url = self.url + '/api/v4/projects/' + urllib.parse.quote(project, safe='') + '/milestones'
        issue_headers = { 'PRIVATE-TOKEN': self.token }
        issue_params = {
            'title': title,
            'description': description,
            'due_date': due_date,
            'start_date': start_date
        }

        return requests.post(issue_url, headers=issue_headers, params=issue_params).json()

    def get_project_issues(self, project, state='opened', labels='', updated_before=None, updated_after=None, iids=None, order_by='created_at', sort='desc', limit=None):
        """ Get all issues """
        self.issues = []
        item_buffer = []
        item_count = 100
        page_count = 1
        updated_after_str = ''
        updated_before_str = ''

        if updated_after is not None:
            updated_after_str = updated_after.isoformat()

        if updated_before is not None:
            updated_before_str = updated_before.isoformat()

        url = self.url + '/api/v4/projects/' + urllib.parse.quote(project, safe='') + '/issues'
        headers = { 'PRIVATE-TOKEN': self.token }
        params = {
            'page': 0,
            'per_page': item_count,
            'state': state,
            'labels': labels,
            'updated_before': updated_before_str,
            'updated_after': updated_after_str,
            'order_by': order_by,
            'sort': sort,
            'scope': 'all'
        }

        if iids and len(iids) > 0:
            params['iids[]'] = list(map(str, iids))

        ctr = 0
        while True:
            # fetch a page of issues
            params['page'] = page_count
            params['per_page'] = item_count

            if limit and limit > 0 and (limit - ctr) > 0 and (limit - ctr) < item_count:
                params['per_page'] = (limit - ctr)
            
            # fetch issues
            r = requests.get(url, params=params, headers=headers)
            item_buffer = r.json()

            for item in item_buffer:
                ctr += 1
                yield item

            # next page until non-full buffer
            page_count += 1
            if (limit and limit > 0 and ctr >= limit) or len(item_buffer) < item_count:
                break

        return

    def get_issue(self, project, issue_iid):
        """ Get a single issue by id """
        url = self.url + '/api/v4/projects/' + urllib.parse.quote(project, safe='') + '/issues/' + str(issue_iid)
        headers = { 'PRIVATE-TOKEN': self.token }
        response = requests.get(url, headers=headers)
        
        if response.status_code == 404:
            return None
        elif response.status_code > 299:
            raise Exception('Unhandled http response code')
        
        return response.json()

    def get_issue_notes(self, project, issue_iid, sort='desc', order_by='updated_at'):
        """ Get notes from a issue """
        item_count = 100
        page_count = 1

        url = self.url + '/api/v4/projects/' + urllib.parse.quote(project, safe='') + '/issues/' + str(issue_iid) + '/notes'
        headers = { 'PRIVATE-TOKEN': self.token }
        params = { 'page': 0, 'per_page': item_count, 'sort': sort, 'order_by': order_by }

        while True:
            # fetch a page of issue notes
            params['page'] = page_count
            r = requests.get(url, params=params, headers=headers)
            item_buffer = r.json()

            for item in item_buffer:
                yield item

            # next page until non-full buffer
            page_count += 1
            if len(item_buffer) < item_count:
                break

        return

    def get_issue_label_events(self, project, issue_iid):
        """ Get label events from a issue """
        item_count = 100
        page_count = 1

        url = self.url + '/api/v4/projects/' + urllib.parse.quote(project, safe='') + '/issues/' + str(issue_iid) + '/resource_label_events'
        headers = { 'PRIVATE-TOKEN': self.token }
        params = { 'page': 0, 'per_page': item_count }

        while True:
            # fetch a page of issue notes
            params['page'] = page_count
            r = requests.get(url, params=params, headers=headers)
            item_buffer = r.json()

            for item in item_buffer:
                yield item

            # next page until non-full buffer
            page_count += 1
            if len(item_buffer) < item_count:
                break

        return

    def post_issue(self, project, title, body, labels=[], assignee_ids=[], due_date=''):
        """ Post a new issue """
        issue_url = self.url + '/api/v4/projects/' + urllib.parse.quote(project, safe='') + '/issues'
        issue_headers = { 'PRIVATE-TOKEN': self.token }
        issue_params = {
            'title': title,
            'labels': ','.join((labels or [])),
            'assignee_ids': (assignee_ids or []),
            'description': body,
            'due_date': (due_date or '')
        }

        return requests.post(issue_url, headers=issue_headers, params=issue_params).json()

    def update_issue(self, project, issue_iid, issue_params={}):
        """ Update a issue """
        issue_url = self.url + '/api/v4/projects/' + urllib.parse.quote(project, safe='') + '/issues/' + str(issue_iid)
        issue_headers = { 'PRIVATE-TOKEN': self.token }

        return requests.put(issue_url, headers=issue_headers, params=issue_params).json()

    def reorder_issue(self, project, issue_iid, move_before_global_id=None, move_after_global_id=None):
        """ Reorder issues """
        issue_url = self.url + '/api/v4/projects/' + urllib.parse.quote(project, safe='') + '/issues/' + str(issue_iid) + '/reorder'
        issue_headers = { 'PRIVATE-TOKEN': self.token }

        reorder_params = {
            'move_after_id': move_after_global_id,
            'move_before_id': move_before_global_id
        }

        return requests.put(issue_url, headers=issue_headers, params=reorder_params).json()

    def post_note(self, project, issue_iid, body):
        """ Post a new note """
        note_url = self.url + '/api/v4/projects/' + urllib.parse.quote(project, safe='') + '/issues/' + str(issue_iid) + '/notes'
        note_headers = { 'PRIVATE-TOKEN': self.token }
        note_params = { 'body': body }
        return requests.post(note_url, headers=note_headers, params=note_params).json()

    def update_note(self, project, issue_iid, note_id, body):
        """ Update existing note """
        note_url = self.url + '/api/v4/projects/' + urllib.parse.quote(project, safe='') + '/issues/' + str(issue_iid) + '/notes/' + str(note_id)
        note_headers = { 'PRIVATE-TOKEN': self.token }
        note_params = { 'body': body }
        return requests.put(note_url, headers=note_headers, params=note_params).json()

    def delete_note(self, project, issue_iid, note_id):
        """ Delete existing note """
        note_url = self.url + '/api/v4/projects/' + urllib.parse.quote(project, safe='') + '/issues/' + str(issue_iid) + '/notes/' + str(note_id)
        note_headers = { 'PRIVATE-TOKEN': self.token }
        requests.delete(note_url, headers=note_headers)
