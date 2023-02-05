# TaskOMat GitLab Issue Bot

This is a script collection to manage GitLab issues.

## Changelog 2022-12-23

- All issues will be set to confidential if they don't have a `Public` label assigned
- The label `Work in Progress` will be removed from closed issues
- Support for starting housekeep.py via Web Hook for a single issue

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
    --milestone-label Wohnung \
    --label-group "low,medium*,high" \
    --label-category "Green,Red,Yellow,Color" \
    --closed-remove-label "Workflow:Work in Progress" \
    --closed-remove-label "Workflow:On Hold" \
    --close-obsolete \
    --lock-closed \
    --assign-closed \
    --set-confidential \
    --notify-due \
    --counters \
    [--issue-iid 42]
```

```mermaid
graph TD
    hk[Housekeep Cron] --> issues[Get all Issues where<br>updated timestamp is<br>older than 15 minutes<br>or a single issue]
    wekhook[Webhook] --> issues
    issues --> assign[Assign all unassigned<br>issues to a specific user]
    issues --> ispublic{Has issue<br>Public label?}
    ispublic -->|Yes| confidential[Set issue<br>to confidential]
    ispublic -->|No| noconfidential[Set issue<br>to not confidential]
    issues --> isdue{Is issue<br>past due?}
    isdue -->|Yes| delduemsg2[Delete existing<br>due mentions]
    issues --> isclosed{Is issue<br>closed?}
    isclosed -->|Yes| delwip[Delete<br>Work in Progress<br>label]
    isclosed -->|Yes| delunass{Issue<br>unassigned?}
    delunass -->|Yes| assclosee[Assign User<br>which closed<br>the issue]
    delwip --> delonhold[Delete<br>On Hold<br>label]
    delonhold --> lock[Lock discussions]
    delduemsg2 --> addue[Create past due<br>mention to assignee]
    isdue -->|No| delduemsg[Delete existing<br>past due mentions]
    issues --> iscounter{Has issue<br>Counter label?}
    issues --> isobsolete{Has issue<br>Obsolete label?}
    isobsolete -->|Yes| close[Close issue]
    iscounter -->|Yes| countit[Process Counter<br>Bot commands]
    issues --> childlabel{child<br>label<br>added?}
    childlabel --> addcat[Add category<br>label]
    issues --> groupdefault[Ensure default<br>label of a label group<br>if no group label<br>exists]
    groupdefault --> groupadded{group label<br>added and<br>other label<br>of the group<br>existent?}
    groupadded -->|Yes| removegrouplabel[Remove all labels<br>of a group except<br>the last added one]
```

### Label Groups

The `--label-group "low,medium*,high"` feature ensures that only the latest label
mentioned in the list is present in the issue. If one label is marked with a `*`,
it will be added automatically of none of the labels are present.

This works similar to the [Scoped Labels of GitLab Premium](https://docs.gitlab.com/ee/user/project/labels.html#scoped-labels).

### Label Categories

The `--label-category "Green,Red,Yellow,Color"` feature ensures that, if `Green`,
`Red` or `Yellow` exists, the `Color` label is added. The `Color` label is removed
if none of the child labels are present.

### Counter

If a issue has a `Counter` label assigned, the housekeep script will look for
commands starting with `!` in notes and creates a statistic from it.

```txt
!countunit km
!countgoal 1000
!count 20
[...]
```

will result in

`TaskOMat:countersummary` :tea: Here is the TaskOMat counter summary:

**Processed:** 65 items
**Time range:** 2022-05-28 - 2022-12-21
**Smallest Amount:** 2.0 km
**Largest Amount:** 102.0 km

**Goal:**
![grand progress](https://progress-bar.dev/123/?scale=100&width=260&color=0072ef&suffix=%25%20%281231km%20of%201000km%29)

| Month | Items | Amount |
|---|---|---|
| 2022-05 | 9 | 162.0 km |
| 2022-06 | 13 :tada: | 383.0 km :tada: |
| 2022-07 | 5 | 108.0 km |
| 2022-08 | 13 | 208.0 km |
| 2022-09 | 12 | 147.0 km |
| 2022-10 | 7 | 124.0 km |
| 2022-11 | 5 | 67.0 km |
| 2022-12 | 1 | 32.0 km |

**Total:** 1231.0 km (+32.0 km last)

### Run by Web Hook

Executing the housekeeping script by a web hook allows a almost-instant
apply of the TaskOMat rules. It will start a new pipeline for each single
modified issue.

The pipeline YAML will extract the issue iid from the
trigger payload and will start housekeep with `--issue-iid $ISSUE_ID`.

```yml
# .gitlab-ci.yml example
stages:
  - task

variables:
  assignee: 2
  # 5 minutes
  updated_min_hk: 0
  # 30 days
  updated_max_hk: 2592000

# -> Templates
.tpl:default:
  image: taskomat:latest
  stage: task
  tags:
    - docker

# -> Tasks
webhook:housekeep:
  extends: .tpl:default
  script:
    # find issue iid
    - 'if [ -z "${TRIGGER_PAYLOAD:-}" ] || [ ! -f "$TRIGGER_PAYLOAD" ]; then echo "Trigger payload file not found."; exit 0; fi'
    #- 'cat $TRIGGER_PAYLOAD'
    - "ISSUE_ID=$(cat $TRIGGER_PAYLOAD | jq '.issue.iid // .object_attributes.iid')"
    - 'if [ "$ISSUE_ID" == "null" ] || [ $ISSUE_ID -le 0 ]; then echo "No issue iid found."; exit 0; fi'
    # execute housekeeper
    - |
      /src/housekeep.py \
        --gitlab-url "$CI_SERVER_URL" \
        --project "$CI_PROJECT_PATH" \
        --assignee $assignee \
        --milestone-label Vereinsarbeit \
        --delay $updated_min_hk \
        --max-updated-age $updated_max_hk \
        --issue-iid $ISSUE_ID
  only:
    refs:
      - master
      - triggers
    variables:
      - $TRIGGER_PAYLOAD
```

Webhook:

- URL: https://git.example.com/api/v4/projects/42/ref/master/trigger/pipeline?token=XXXXXXXXXXXXXXXXX
- Comments
- Confidential comments
- Issue events
- Confidential issues events
- Enable SSL verification

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
    issue --> top["Move issue to top<br>(for boards)"]
    top --> related[Create a list of<br>related issues]
```
