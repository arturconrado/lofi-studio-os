from studio.creator_plan_versions import content_hash, revision_data


def test_creator_plan_hash_is_stable_and_content_sensitive():
    assert content_hash({'title':'Rainy coding','hours':2})==content_hash({'hours':2,'title':'Rainy coding'})
    assert content_hash({'title':'Rainy coding','hours':2})!=content_hash({'title':'Snowy coding','hours':2})


def test_mutable_artifact_state_does_not_change_editorial_revision_hash():
    proposal={'title':'Rainy coding','hours':2}
    submitting=proposal|{'production_assets':{'asset-1':{'state':'SUBMITTING','sha256':'a'*64}}}
    approved=proposal|{'production_assets':{'asset-1':{'state':'APPROVED','sha256':'a'*64}}}
    edited=proposal|{'title':'Snowy coding','production_assets':approved['production_assets']}
    assert revision_data(submitting)==proposal
    assert content_hash(revision_data(submitting))==content_hash(revision_data(approved))
    assert content_hash(revision_data(edited))!=content_hash(revision_data(approved))
