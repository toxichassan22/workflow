"""The live state of a project file — a tiny read the open workspace polls.

A merge by somebody else changes the file under the people who still have it
open. The workspace asks for the state of the file it has open (the revision,
who changed it last, the state of the section badges) and acts on it: with
nothing unsaved on this side the file is taken again, and with unsaved edits
the next save merges instead of overwriting.
"""


@app.route('/api/project-draft/<draft_id>/state', methods=['GET'])
@require_auth
def api_draft_live_state(draft_id):
    """The revision of a project file, who changed it last, and its badges."""
    # Whoever may open the file may follow it. This answers "did the file move
    # under me", not "who may read the history": the stricter history rule
    # (owner, approver, assignee) stays on the commit and branch routes. A
    # colleague who can open the project must be able to see it move, or the
    # workspace would only follow the file for its owner.
    draft = db.get_project_draft_state(g.tenant_id, draft_id)
    if not draft or not db.user_may_access_draft(g.user_id, draft):
        return jsonify({'error': 'No project draft found'}), 404
    try:
        since = int(request.args.get('since') or 0)
    except (TypeError, ValueError):
        since = 0
    revision = int(draft.get('revision') or 0)
    commits = db.list_draft_commits(g.tenant_id, draft_id, limit=1)
    last = commits[0] if commits else None
    return jsonify({
        'success': True,
        'draftId': draft_id,
        'revision': revision,
        'changed': revision > since,
        'updatedAt': draft.get('updated_at') or '',
        'lastCommit': ({
            'kind': last.get('kind') or '',
            'author': last.get('author_name') or last.get('author_id') or '',
            'createdAt': last.get('created_at') or '',
            'message': last.get('message') or '',
        } if last else None),
        'sectionStatuses': draft.get('section_statuses') or {},
        'openBranches': db.count_open_draft_branches(g.tenant_id, draft_id),
    })
