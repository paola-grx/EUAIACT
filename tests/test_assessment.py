from euaiact import assessment as a
from euaiact import inventory


def keys(path):
    return [i.module_key for i in path.items]


def test_casual_chatbot_user_gets_core_only(session):
    p = inventory.add_person(session, "t", name="Casey")
    inventory.record_assessment(session, p, "t", technical_background="intermediate", ai_experience="some")
    bot = inventory.add_system(session, "t", name="Copilot", risk_class="minimal")
    inventory.assign(session, p, bot, "casual_user", "t")
    path = a.build_learning_path(p)
    assert keys(path) == [a.CORE]
    assert path.depth == "standard"


def test_minimal_risk_still_requires_literacy(session):
    """Art. 4 applies regardless of risk class: even minimal-risk users get the core module."""
    p = inventory.add_person(session, "t", name="Min")
    bot = inventory.add_system(session, "t", name="Spellcheck AI", risk_class="minimal")
    inventory.assign(session, p, bot, "casual_user", "t")
    assert a.CORE in a.build_learning_path(p).required_keys()


def test_overseer_of_high_risk_deployed_system(session):
    p = inventory.add_person(session, "t", name="Olga")
    inventory.record_assessment(session, p, "t", technical_background="none", ai_experience="none")
    s = inventory.add_system(session, "t", name="CV ranker", risk_class="high", org_role="deployer",
                             affected_persons=["job candidates"])
    inventory.assign(session, p, s, "human_overseer", "t")
    path = a.build_learning_path(p)
    assert keys(path) == [a.PRIMER, a.CORE, a.OVERSEER, a.DEPLOYER_HR, a.AFFECTED]
    assert path.depth == "foundation"
    assert any("job candidates" in r for r in path.item(a.AFFECTED).reasons)


def test_developer_of_generative_system_advanced(session):
    p = inventory.add_person(session, "t", name="Dev")
    inventory.record_assessment(session, p, "t", technical_background="advanced", ai_experience="extensive")
    s = inventory.add_system(session, "t", name="Writer", risk_class="limited", org_role="provider", generative=True)
    inventory.assign(session, p, s, "developer", "t")
    path = a.build_learning_path(p)
    assert keys(path) == [a.CORE, a.DEVELOPER, a.GENAI]
    assert path.depth == "advanced"


def test_decision_maker_on_high_risk_gets_oversight(session):
    p = inventory.add_person(session, "t", name="Dee")
    s = inventory.add_system(session, "t", name="Credit", risk_class="high", org_role="deployer")
    inventory.assign(session, p, s, "decision_maker", "t")
    assert {a.OVERSEER, a.DEPLOYER_HR} <= a.build_learning_path(p).required_keys()


def test_sme_mode_minimum_viable_programme(session):
    p = inventory.add_person(session, "t", name="Sam")
    inventory.record_assessment(session, p, "t", technical_background="basic", ai_experience="some")
    s = inventory.add_system(session, "t", name="Chat", risk_class="limited", generative=True,
                             affected_persons=["customers"])
    inventory.assign(session, p, s, "operator", "t")
    path = a.build_learning_path(p, sme_mode=True)
    assert path.required_keys() == {a.SME, a.GENAI}
    assert {i.module_key for i in path.items if i.optional} == {a.PRIMER, a.AFFECTED}


def test_path_without_assessment_is_flagged(session):
    p = inventory.add_person(session, "t", name="New")
    path = a.build_learning_path(p)
    assert any("No needs assessment" in n for n in path.notes)
