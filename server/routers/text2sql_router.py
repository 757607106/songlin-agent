"""Text2SQL API Router - 数据库连接、Schema、值映射管理接口"""

from fastapi import APIRouter, Body, Depends, HTTPException

from server.utils.auth_middleware import get_admin_user
from src.services.skill_generation_service import skill_generation_service
from src.services.text2sql_service import text2sql_service
from src.storage.postgres.models_business import User
from src.utils import logger

text2sql = APIRouter(prefix="/text2sql", tags=["text2sql"])


# =============================================================================
# === 数据库连接管理 ===
# =============================================================================


@text2sql.get("/connections")
async def get_connections(current_user: User = Depends(get_admin_user)):
    """获取当前部门的所有数据库连接"""
    connections = await text2sql_service.get_connections(current_user.department_id)
    return {"status": "success", "data": connections}


@text2sql.get("/connections/{connection_id}")
async def get_connection(connection_id: int, current_user: User = Depends(get_admin_user)):
    """获取单个数据库连接详情"""
    conn = await text2sql_service.get_connection(connection_id)
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")
    # 检查部门权限
    if conn["department_id"] != current_user.department_id and current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="无权访问此连接")
    return {"status": "success", "data": conn}


@text2sql.post("/connections")
async def create_connection(
    name: str = Body(...),
    db_type: str = Body(...),
    host: str = Body(None),
    port: int = Body(None),
    database: str = Body(...),
    username: str = Body(None),
    password: str = Body(None),
    extra_params: dict = Body(None),
    current_user: User = Depends(get_admin_user),
):
    """创建数据库连接"""
    data = {
        "department_id": current_user.department_id,
        "name": name,
        "db_type": db_type,
        "host": host,
        "port": port,
        "database": database,
        "username": username,
        "password": password,
        "extra_params": extra_params,
        "created_by": current_user.user_id,
        "updated_by": current_user.user_id,
    }
    conn = await text2sql_service.create_connection(data)
    logger.info(f"User {current_user.user_id} created db connection: {name}")
    return {"status": "success", "data": conn}


@text2sql.put("/connections/{connection_id}")
async def update_connection(
    connection_id: int,
    name: str = Body(None),
    db_type: str = Body(None),
    host: str = Body(None),
    port: int = Body(None),
    database: str = Body(None),
    username: str = Body(None),
    password: str = Body(None),
    extra_params: dict = Body(None),
    is_active: bool = Body(None),
    current_user: User = Depends(get_admin_user),
):
    """更新数据库连接"""
    # 检查权限
    existing = await text2sql_service.get_connection(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="连接不存在")
    if existing["department_id"] != current_user.department_id and current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="无权修改此连接")

    data = {"updated_by": current_user.user_id}
    if name is not None:
        data["name"] = name
    if db_type is not None:
        data["db_type"] = db_type
    if host is not None:
        data["host"] = host
    if port is not None:
        data["port"] = port
    if database is not None:
        data["database"] = database
    if username is not None:
        data["username"] = username
    if password is not None:
        data["password"] = password
    if extra_params is not None:
        data["extra_params"] = extra_params
    if is_active is not None:
        data["is_active"] = is_active

    conn = await text2sql_service.update_connection(connection_id, data)
    return {"status": "success", "data": conn}


@text2sql.delete("/connections/{connection_id}")
async def delete_connection(connection_id: int, current_user: User = Depends(get_admin_user)):
    """删除数据库连接"""
    existing = await text2sql_service.get_connection(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="连接不存在")
    if existing["department_id"] != current_user.department_id and current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="无权删除此连接")

    await text2sql_service.delete_connection(connection_id)
    logger.info(f"User {current_user.user_id} deleted db connection: {connection_id}")
    return {"status": "success", "message": "删除成功"}


@text2sql.post("/connections/{connection_id}/test")
async def test_connection(connection_id: int, current_user: User = Depends(get_admin_user)):
    """测试数据库连接"""
    existing = await text2sql_service.get_connection(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="连接不存在")
    if existing["department_id"] != current_user.department_id and current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="无权访问此连接")

    result = await text2sql_service.test_connection(connection_id)
    return {"status": "success" if result["success"] else "error", **result}


# =============================================================================
# === Schema 管理 ===
# =============================================================================


@text2sql.get("/connections/{connection_id}/schema")
async def get_schema(connection_id: int, current_user: User = Depends(get_admin_user)):
    """获取连接的 Schema 信息"""
    existing = await text2sql_service.get_connection(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="连接不存在")
    if existing["department_id"] != current_user.department_id and current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="无权访问此连接")

    schema = await text2sql_service.get_schema(connection_id)
    return {"status": "success", "data": schema}


@text2sql.post("/connections/{connection_id}/schema/discover")
async def discover_schema(connection_id: int, current_user: User = Depends(get_admin_user)):
    """从数据库发现 Schema"""
    existing = await text2sql_service.get_connection(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="连接不存在")
    if existing["department_id"] != current_user.department_id and current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="无权访问此连接")

    try:
        schema = await text2sql_service.discover_schema(connection_id)
        logger.info(f"User {current_user.user_id} discovered schema for connection: {connection_id}")
        return {"status": "success", "data": schema}
    except Exception as e:
        logger.error(f"Schema discovery failed: {e}")
        raise HTTPException(status_code=500, detail=f"Schema 发现失败: {e}")


@text2sql.put("/schema/tables/{table_id}/position")
async def update_table_position(
    table_id: int,
    position_x: int = Body(...),
    position_y: int = Body(...),
    current_user: User = Depends(get_admin_user),
):
    """更新表的位置（ReactFlow 拖拽）"""
    table = await text2sql_service.update_table_position(table_id, position_x, position_y)
    if not table:
        raise HTTPException(status_code=404, detail="表不存在")
    return {"status": "success", "data": table}


@text2sql.put("/schema/tables/{table_id}")
async def update_table(
    table_id: int,
    table_comment: str = Body(None, embed=True),
    current_user: User = Depends(get_admin_user),
):
    """更新表信息"""
    data = {}
    if table_comment is not None:
        data["table_comment"] = table_comment

    table = await text2sql_service.update_table(table_id, data)
    if not table:
        raise HTTPException(status_code=404, detail="表不存在")
    return {"status": "success", "data": table}


@text2sql.delete("/schema/tables/{table_id}")
async def delete_table(table_id: int, current_user: User = Depends(get_admin_user)):
    """删除表（从 Schema 中移除）"""
    deleted = await text2sql_service.delete_table(table_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="表不存在")
    return {"status": "success", "message": "删除成功"}


@text2sql.put("/schema/columns/{column_id}")
async def update_column(
    column_id: int,
    column_comment: str = Body(None, embed=True),
    current_user: User = Depends(get_admin_user),
):
    """更新列信息"""
    data = {}
    if column_comment is not None:
        data["column_comment"] = column_comment

    column = await text2sql_service.update_column(column_id, data)
    if not column:
        raise HTTPException(status_code=404, detail="列不存在")
    return {"status": "success", "data": column}


# =============================================================================
# === 关系管理 ===
# =============================================================================


@text2sql.post("/connections/{connection_id}/relationships")
async def create_relationship(
    connection_id: int,
    source_table: str = Body(...),
    source_column: str = Body(...),
    target_table: str = Body(...),
    target_column: str = Body(...),
    relationship_type: str = Body("many_to_one"),
    current_user: User = Depends(get_admin_user),
):
    """创建关系"""
    existing = await text2sql_service.get_connection(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="连接不存在")
    if existing["department_id"] != current_user.department_id and current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="无权访问此连接")

    data = {
        "connection_id": connection_id,
        "source_table": source_table,
        "source_column": source_column,
        "target_table": target_table,
        "target_column": target_column,
        "relationship_type": relationship_type,
    }
    relationship = await text2sql_service.create_relationship(data)
    return {"status": "success", "data": relationship}


@text2sql.put("/relationships/{relationship_id}")
async def update_relationship(
    relationship_id: int,
    relationship_type: str = Body(None, embed=True),
    current_user: User = Depends(get_admin_user),
):
    """更新关系"""
    data = {}
    if relationship_type is not None:
        data["relationship_type"] = relationship_type

    relationship = await text2sql_service.update_relationship(relationship_id, data)
    if not relationship:
        raise HTTPException(status_code=404, detail="关系不存在")
    return {"status": "success", "data": relationship}


@text2sql.delete("/relationships/{relationship_id}")
async def delete_relationship(relationship_id: int, current_user: User = Depends(get_admin_user)):
    """删除关系"""
    deleted = await text2sql_service.delete_relationship(relationship_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="关系不存在")
    return {"status": "success", "message": "删除成功"}


# =============================================================================
# === 值映射管理 ===
# =============================================================================


@text2sql.get("/connections/{connection_id}/value-mappings")
async def get_value_mappings(connection_id: int, current_user: User = Depends(get_admin_user)):
    """获取连接的所有值映射"""
    existing = await text2sql_service.get_connection(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="连接不存在")
    if existing["department_id"] != current_user.department_id and current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="无权访问此连接")

    mappings = await text2sql_service.get_value_mappings(connection_id)
    return {"status": "success", "data": mappings}


@text2sql.post("/connections/{connection_id}/value-mappings")
async def create_value_mapping(
    connection_id: int,
    table_name: str = Body(...),
    column_name: str = Body(...),
    natural_value: str = Body(...),
    db_value: str = Body(...),
    description: str = Body(None),
    current_user: User = Depends(get_admin_user),
):
    """创建值映射"""
    existing = await text2sql_service.get_connection(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="连接不存在")
    if existing["department_id"] != current_user.department_id and current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="无权访问此连接")

    data = {
        "connection_id": connection_id,
        "table_name": table_name,
        "column_name": column_name,
        "natural_value": natural_value,
        "db_value": db_value,
        "description": description,
        "created_by": current_user.user_id,
    }
    mapping = await text2sql_service.create_value_mapping(data)
    return {"status": "success", "data": mapping}


@text2sql.post("/connections/{connection_id}/value-mappings/batch")
async def batch_create_value_mappings(
    connection_id: int,
    mappings: list[dict] = Body(...),
    current_user: User = Depends(get_admin_user),
):
    """批量创建值映射"""
    existing = await text2sql_service.get_connection(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="连接不存在")
    if existing["department_id"] != current_user.department_id and current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="无权访问此连接")

    mappings_data = []
    for m in mappings:
        mappings_data.append(
            {
                "connection_id": connection_id,
                "table_name": m["table_name"],
                "column_name": m["column_name"],
                "natural_value": m["natural_value"],
                "db_value": m["db_value"],
                "description": m.get("description"),
                "created_by": current_user.user_id,
            }
        )

    result = await text2sql_service.batch_create_value_mappings(mappings_data)
    return {"status": "success", "data": result}


@text2sql.delete("/value-mappings/{mapping_id}")
async def delete_value_mapping(mapping_id: int, current_user: User = Depends(get_admin_user)):
    """删除值映射"""
    deleted = await text2sql_service.delete_value_mapping(mapping_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="值映射不存在")
    return {"status": "success", "message": "删除成功"}


# =============================================================================
# === Skills 管理 ===
# =============================================================================


@text2sql.post("/connections/{connection_id}/skills/generate")
async def generate_reporter_skill(
    connection_id: int,
    business_scenario: str = Body(...),
    target_metrics: list[str] | None = Body(None),
    constraints: list[str] | None = Body(None),
    current_user: User = Depends(get_admin_user),
):
    existing = await text2sql_service.get_connection(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="连接不存在")
    if existing["department_id"] != current_user.department_id and current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="无权访问此连接")
    try:
        result = await skill_generation_service.generate_reporter_skill(
            department_id=current_user.department_id,
            connection_id=connection_id,
            business_scenario=business_scenario,
            target_metrics=target_metrics or [],
            constraints=constraints or [],
            created_by=str(current_user.id),
        )
        return {"status": "success", "data": result}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@text2sql.get("/connections/{connection_id}/skills")
async def list_reporter_skills(connection_id: int, current_user: User = Depends(get_admin_user)):
    existing = await text2sql_service.get_connection(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="连接不存在")
    if existing["department_id"] != current_user.department_id and current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="无权访问此连接")
    result = await skill_generation_service.list_reporter_skills(
        department_id=current_user.department_id,
        connection_id=connection_id,
    )
    return {"status": "success", "data": result}


@text2sql.post("/connections/{connection_id}/skills/{skill_id}/publish")
async def publish_reporter_skill(connection_id: int, skill_id: str, current_user: User = Depends(get_admin_user)):
    existing = await text2sql_service.get_connection(connection_id)
    if not existing:
        raise HTTPException(status_code=404, detail="连接不存在")
    if existing["department_id"] != current_user.department_id and current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="无权访问此连接")
    try:
        result = await skill_generation_service.publish_reporter_skill(
            department_id=current_user.department_id,
            connection_id=connection_id,
            skill_id=skill_id,
            updated_by=str(current_user.id),
        )
        return {"status": "success", "data": result}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
