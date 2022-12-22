# TaskOMat GitLab Issue Bot

This is a script collection to manage GitLab issues.

## Housekeeping

This cron ensures certain rules on all issues.

```sh
# from a gitlab-ci pipeline
# uses the buildin variables
#
# also requires the TASKOMAT_TOKEN variable
# which must contain a valid access token of the
# bot user in the CI Pipeline Variables

./housekeep.py --gitlab-url "$CI_SERVER_URL" \
    --project "$CI_PROJECT_PATH" \
    --assignee $assignee \
    --delay 900 \
    --max-updated-age 2592000 \
    --milestone-label Bürokratie \
    --milestone-label Wohnung
```

```mermaid
graph TD
    hk[Housekeep Cron] --> issues[Get all Issues where<br>updated timestamp is<br>older than 15 minutes]
    issues --> assign[Assign all unassigned<br>issues to a specific user]
    issues --> milestone[Summarize issues tagged<br>with specific tags in<br>milestones to show a time<br>tracking summary for this tag]
    issues --> confidential[Set issues<br>to confidential]
    issues --> isdue{Is issue<br>past due?}
    isdue -->|Yes| delduemsg2[Delete existing<br>due mentions]
    issues --> isclosed{Is issue<br>closed?}
    isclosed -->|Yes| delwip[Delete<br>Work in Progress<br>label]
    isclosed --> |Yes| lock[Lock discussions<br>for closed issues]
    delduemsg2 --> addue[Create past due<br>mention to assignee]
    isdue -->|No| delduemsg[Delete existing<br>past due mentions]
```

## TaskOMat

This script creates issues from YAML files. When
the specific issue already/still exists it creates
just a mention to the assignee.

```sh
# from a gitlab-ci pipeline
# uses buildin variables and pipeline scheduler variables
#
# also requires the TASKOMAT_TOKEN variable
# which must contain a valid access token of the
# bot user in the CI Pipeline Variables

./taskomat.py --gitlab-url "$CI_SERVER_URL" \
    --project "$CI_PROJECT_PATH" \
    --collection-dir ./$CRON_COLLECTION \
    --max-updated-age 7776000
```

```mermaid
graph TD
    tm[TaskOMat Cron] --> check{Issue still exists?}
    check -->|Yes| note[Create a note<br>to mention assignee]
    check -->|No| issue[Create a new<br>issue based<br>von YAML config]
    issue --> related[Create a list of<br>related issues]
```
