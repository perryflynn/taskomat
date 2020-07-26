import requests
import urllib.parse

class GitLabApi:
    """ GitLab API functions """

    def __init__(self, gitlab_url, gitlab_token):
        """ Initialize class """
        self.url = gitlab_url
        self.token = gitlab_token

    def get_project_issues(self, project, state='opened', labels=''):
        """ Get all issues """
        self.issues = []
        item_buffer = []
        item_count = 100
        page_count = 1

        url = self.url + '/api/v4/projects/' + urllib.parse.quote(project, safe='') + '/issues'
        headers = { 'PRIVATE-TOKEN': self.token }
        params = { 'page': 0, 'per_page': item_count, 'state': state, 'labels': labels }

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

    def get_issue(self, project, issue_iid):
        """ Get a single issue by id """
        url = self.url + '/api/v4/projects/' + urllib.parse.quote(project, safe='') + '/issues/' + str(issue_iid)
        headers = { 'PRIVATE-TOKEN': self.token }
        return requests.get(url, headers=headers).json()

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
