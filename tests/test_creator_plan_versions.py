from studio.creator_plan_versions import content_hash


def test_creator_plan_hash_is_stable_and_content_sensitive():
    assert content_hash({'title':'Rainy coding','hours':2})==content_hash({'hours':2,'title':'Rainy coding'})
    assert content_hash({'title':'Rainy coding','hours':2})!=content_hash({'title':'Snowy coding','hours':2})
