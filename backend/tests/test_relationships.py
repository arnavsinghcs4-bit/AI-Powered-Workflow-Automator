"""No-DB test for SQLAlchemy mapper configuration - verifies relationship foreign_keys are unambiguous."""


def test_pipeline_relationships_configure():
    """Test that all Pipeline/PipelineVersion relationships configure without ambiguity.

    This runs configure_mappers() which will raise an error if foreign_keys
    are ambiguous (e.g. multiple FK paths between the same two tables).
    """
    from sqlalchemy.orm import configure_mappers

    # Import all models to register them
    from app.pipelines.models import Pipeline, PipelineVersion, Run

    # This will raise if any relationship has ambiguous foreign_keys
    configure_mappers()

    # Verify specific relationships resolve correctly
    # Pipeline.versions -> PipelineVersion.pipeline_id
    assert Pipeline.versions.property.mapper.class_ is PipelineVersion
    assert Pipeline.versions.property.direction.name == "ONETOMANY"

    # Pipeline.current_version -> PipelineVersion.id
    assert Pipeline.current_version.property.mapper.class_ is PipelineVersion
    assert Pipeline.current_version.property.direction.name == "MANYTOONE"
    assert Pipeline.current_version.property.post_update is True

    # PipelineVersion.pipeline -> Pipeline.id
    assert PipelineVersion.pipeline.property.mapper.class_ is Pipeline
    assert PipelineVersion.pipeline.property.direction.name == "MANYTOONE"
    # foreign_keys is on the Column, not the relationship property
    fk = list(PipelineVersion.pipeline_id.foreign_keys)[0]
    assert fk.target_fullname == "pipelines.id"

    # Run.pipeline -> Pipeline.id
    assert Run.pipeline.property.mapper.class_ is Pipeline
    assert Run.pipeline.property.direction.name == "MANYTOONE"
    fk = list(Run.pipeline_id.foreign_keys)[0]
    assert fk.target_fullname == "pipelines.id"

    # Run.version -> PipelineVersion.id
    assert Run.version.property.mapper.class_ is PipelineVersion
    assert Run.version.property.direction.name == "MANYTOONE"
    fk = list(Run.version_id.foreign_keys)[0]
    assert fk.target_fullname == "pipeline_versions.id"


def test_user_relationships_configure():
    """Test User relationships still configure."""
    from sqlalchemy.orm import configure_mappers

    from app.models import User

    configure_mappers()
    assert User.pipelines.property.mapper.class_.__name__ == "Pipeline"
    assert User.runs.property.mapper.class_.__name__ == "Run"
