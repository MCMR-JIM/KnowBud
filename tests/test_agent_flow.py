from src.agent.graph_curator import GraphCurator
from src.agent.orchestrator import AgentOrchestrator
from src.agent.topic_router import TopicRouter
from src.core.enums import LearningPhase
from src.core.models import AppState, CurriculumConfig, LearningState, NodeMastery, TopicNode, UserProfile
from datetime import datetime, timedelta, timezone


def make_state() -> AppState:
    return AppState(
        profile=UserProfile(student_id="u1", display_name="demo"),
        learning=LearningState(current_phase=LearningPhase.LEARNING, current_topic_id="topic_dino"),
        curriculum=CurriculumConfig(
            topics=[
                TopicNode(topic_id="topic_dino", title="恐龙灭绝原因", difficulty=1, prerequisite_ids=[], tags=[]),
                TopicNode(topic_id="topic_fossil", title="化石形成过程", difficulty=1, prerequisite_ids=[], tags=[]),
            ]
        ),
    )


def test_topic_router_has_inertia_on_nearby_scores() -> None:
    state = make_state()
    router = TopicRouter(inertia_bonus=0.2, switch_margin=0.25, min_score=0.05)

    result = router.route(user_text="恐龙形成过程", current_topic_id=state.learning.current_topic_id, topics=state.curriculum.topics)
    assert result.target_topic_id == "topic_dino"
    assert result.switched is False


def test_graph_curator_rejects_duplicate_title() -> None:
    state = make_state()
    curator = GraphCurator()
    proposal = curator.propose_from_question(question_text="恐龙灭绝原因是什么", current_topic_id="topic_dino")

    applied, new_topic_id = curator.auto_review_and_apply(proposal=proposal, curriculum=state.curriculum)
    assert applied is False
    assert new_topic_id is None
    assert proposal.status.value == "rejected"


def test_orchestrator_adds_new_topic_for_off_topic_question() -> None:
    state = make_state()
    orchestrator = AgentOrchestrator()

    result = orchestrator.process_turn(state=state, user_text="黑洞怎么形成")
    assert result.should_answer_directly is True
    assert result.proposal is not None
    assert any("黑洞" in t.title for t in state.curriculum.topics)
    created = next(t for t in state.curriculum.topics if "黑洞" in t.title)
    assert "shadow" in created.tags


def test_graph_curator_blocks_cross_subject_requires() -> None:
    curator = GraphCurator()
    curriculum = CurriculumConfig(
        topics=[
            TopicNode(topic_id="math_1", title="四则运算", difficulty=1, prerequisite_ids=[], tags=["subject:math"]),
            TopicNode(topic_id="bio_1", title="恐龙灭绝", difficulty=1, prerequisite_ids=[], tags=["subject:science"]),
        ]
    )
    proposal = curator.propose_from_question(question_text="跨学科节点", current_topic_id="math_1")
    proposal.parent_node_ids = ["math_1", "bio_1"]

    applied, _topic_id = curator.auto_review_and_apply(proposal=proposal, curriculum=curriculum)
    assert applied is False
    assert proposal.status.value == "rejected"


def test_graph_curator_can_allow_cross_subject_requires_by_policy() -> None:
    curator = GraphCurator(allow_cross_subject_requires=True)
    curriculum = CurriculumConfig(
        topics=[
            TopicNode(topic_id="math_1", title="四则运算", difficulty=1, prerequisite_ids=[], tags=["subject:math"]),
            TopicNode(topic_id="bio_1", title="恐龙灭绝", difficulty=1, prerequisite_ids=[], tags=["subject:science"]),
        ]
    )
    proposal = curator.propose_from_question(question_text="跨学科节点", current_topic_id="math_1")
    proposal.parent_node_ids = ["math_1", "bio_1"]

    applied, topic_id = curator.auto_review_and_apply(proposal=proposal, curriculum=curriculum)
    assert applied is True
    assert topic_id is not None
    assert proposal.status.value == "shadow"


def test_orchestrator_off_topic_in_explore_window_no_proposal() -> None:
    state = make_state()
    state.learning.explore_window_until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    orchestrator = AgentOrchestrator()

    result = orchestrator.process_turn(state=state, user_text="黑洞怎么形成")
    assert result.should_answer_directly is True
    assert result.explore_window_active is True
    assert result.proposal is None


def test_topic_router_respects_prerequisite_unlock_threshold() -> None:
    router = TopicRouter(min_score=0.4, unlock_depth_threshold=1)
    topics = [
        TopicNode(topic_id="t_base", title="恐龙灭绝原因", difficulty=1, prerequisite_ids=[], tags=[]),
        TopicNode(topic_id="t_adv", title="小行星撞击模型", difficulty=2, prerequisite_ids=["t_base"], tags=[]),
    ]

    locked = router.route(
        user_text="小行星撞击模型",
        current_topic_id="t_base",
        topics=topics,
        mastery_map={},
    )
    assert locked.off_topic is True
    assert locked.target_topic_id == "t_base"

    unlocked = router.route(
        user_text="小行星撞击模型",
        current_topic_id="t_base",
        topics=topics,
        mastery_map={"t_base": NodeMastery(depth_level=1)},
    )
    assert unlocked.off_topic is False
    assert unlocked.target_topic_id == "t_adv"


def test_graph_curator_rejects_missing_parent_node() -> None:
    state = make_state()
    curator = GraphCurator()
    proposal = curator.propose_from_question(
        question_text="板块运动如何导致火山喷发",
        current_topic_id="topic_dino",
        topics=state.curriculum.topics,
    )
    proposal.parent_node_ids = ["topic_missing"]

    applied, new_topic_id = curator.auto_review_and_apply(proposal=proposal, curriculum=state.curriculum)
    assert applied is False
    assert new_topic_id is None
    assert proposal.status.value == "rejected"


def test_graph_curator_generates_mastery_followups() -> None:
    state = make_state()
    curator = GraphCurator()
    topic = state.curriculum.topics[0]

    proposals = curator.propose_mastery_followups(topic=topic, curriculum=state.curriculum, limit=1)
    assert len(proposals) == 1
    assert proposals[0].trigger == "mastery_expand"

    applied, new_topic_id = curator.auto_review_and_apply(proposal=proposals[0], curriculum=state.curriculum)
    assert applied is True
    assert new_topic_id is not None
