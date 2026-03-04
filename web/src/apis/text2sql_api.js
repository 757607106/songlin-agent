/**
 * Text2SQL API - 数据库连接、Schema、值映射管理接口
 */

import { apiAdminGet, apiAdminPost, apiAdminPut, apiAdminDelete } from './base'

const BASE_URL = '/api/text2sql'

// =============================================================================
// === 数据库连接管理 ===
// =============================================================================

/**
 * 获取当前部门的所有数据库连接
 * @returns {Promise<{status: string, data: Array}>}
 */
export function getConnections() {
  return apiAdminGet(`${BASE_URL}/connections`)
}

/**
 * 获取单个数据库连接详情
 * @param {number} connectionId - 连接ID
 * @returns {Promise<{status: string, data: Object}>}
 */
export function getConnection(connectionId) {
  return apiAdminGet(`${BASE_URL}/connections/${connectionId}`)
}

/**
 * 创建数据库连接
 * @param {Object} data - 连接配置
 * @param {string} data.name - 连接名称
 * @param {string} data.db_type - 数据库类型 (mysql/postgresql/sqlite)
 * @param {string} [data.host] - 主机地址
 * @param {number} [data.port] - 端口
 * @param {string} data.database - 数据库名
 * @param {string} [data.username] - 用户名
 * @param {string} [data.password] - 密码
 * @param {Object} [data.extra_params] - 额外连接参数
 * @returns {Promise<{status: string, data: Object}>}
 */
export function createConnection(data) {
  return apiAdminPost(`${BASE_URL}/connections`, data)
}

/**
 * 更新数据库连接
 * @param {number} connectionId - 连接ID
 * @param {Object} data - 更新的配置
 * @returns {Promise<{status: string, data: Object}>}
 */
export function updateConnection(connectionId, data) {
  return apiAdminPut(`${BASE_URL}/connections/${connectionId}`, data)
}

/**
 * 删除数据库连接
 * @param {number} connectionId - 连接ID
 * @returns {Promise<{status: string, message: string}>}
 */
export function deleteConnection(connectionId) {
  return apiAdminDelete(`${BASE_URL}/connections/${connectionId}`)
}

/**
 * 测试数据库连接
 * @param {number} connectionId - 连接ID
 * @returns {Promise<{status: string, success: boolean, message: string}>}
 */
export function testConnection(connectionId) {
  return apiAdminPost(`${BASE_URL}/connections/${connectionId}/test`)
}

// =============================================================================
// === Schema 管理 ===
// =============================================================================

/**
 * 获取连接的 Schema 信息
 * @param {number} connectionId - 连接ID
 * @returns {Promise<{status: string, data: {tables: Array, relationships: Array}}>}
 */
export function getSchema(connectionId) {
  return apiAdminGet(`${BASE_URL}/connections/${connectionId}/schema`)
}

/**
 * 从数据库发现 Schema
 * @param {number} connectionId - 连接ID
 * @returns {Promise<{status: string, data: {tables: Array, relationships: Array}}>}
 */
export function discoverSchema(connectionId) {
  return apiAdminPost(`${BASE_URL}/connections/${connectionId}/schema/discover`)
}

/**
 * 更新表的位置（ReactFlow 拖拽）
 * @param {number} tableId - 表ID
 * @param {number} positionX - X坐标
 * @param {number} positionY - Y坐标
 * @returns {Promise<{status: string, data: Object}>}
 */
export function updateTablePosition(tableId, positionX, positionY) {
  return apiAdminPut(`${BASE_URL}/schema/tables/${tableId}/position`, {
    position_x: positionX,
    position_y: positionY
  })
}

/**
 * 更新表信息
 * @param {number} tableId - 表ID
 * @param {Object} data - 更新的信息
 * @param {string} [data.table_comment] - 表注释
 * @returns {Promise<{status: string, data: Object}>}
 */
export function updateTable(tableId, data) {
  return apiAdminPut(`${BASE_URL}/schema/tables/${tableId}`, data)
}

/**
 * 删除表（从 Schema 中移除）
 * @param {number} tableId - 表ID
 * @returns {Promise<{status: string, message: string}>}
 */
export function deleteSchemaTable(tableId) {
  return apiAdminDelete(`${BASE_URL}/schema/tables/${tableId}`)
}

/**
 * 更新列信息
 * @param {number} columnId - 列ID
 * @param {Object} data - 更新的信息
 * @param {string} [data.column_comment] - 列注释
 * @returns {Promise<{status: string, data: Object}>}
 */
export function updateColumn(columnId, data) {
  return apiAdminPut(`${BASE_URL}/schema/columns/${columnId}`, data)
}

// =============================================================================
// === 关系管理 ===
// =============================================================================

/**
 * 创建关系
 * @param {number} connectionId - 连接ID
 * @param {Object} data - 关系配置
 * @param {string} data.source_table - 源表名
 * @param {string} data.source_column - 源列名
 * @param {string} data.target_table - 目标表名
 * @param {string} data.target_column - 目标列名
 * @param {string} [data.relationship_type] - 关系类型
 * @returns {Promise<{status: string, data: Object}>}
 */
export function createRelationship(connectionId, data) {
  return apiAdminPost(`${BASE_URL}/connections/${connectionId}/relationships`, data)
}

/**
 * 更新关系
 * @param {number} relationshipId - 关系ID
 * @param {Object} data - 更新的信息
 * @param {string} [data.relationship_type] - 关系类型
 * @returns {Promise<{status: string, data: Object}>}
 */
export function updateRelationship(relationshipId, data) {
  return apiAdminPut(`${BASE_URL}/relationships/${relationshipId}`, data)
}

/**
 * 删除关系
 * @param {number} relationshipId - 关系ID
 * @returns {Promise<{status: string, message: string}>}
 */
export function deleteRelationship(relationshipId) {
  return apiAdminDelete(`${BASE_URL}/relationships/${relationshipId}`)
}

// =============================================================================
// === 值映射管理 ===
// =============================================================================

/**
 * 获取连接的所有值映射
 * @param {number} connectionId - 连接ID
 * @returns {Promise<{status: string, data: Array}>}
 */
export function getValueMappings(connectionId) {
  return apiAdminGet(`${BASE_URL}/connections/${connectionId}/value-mappings`)
}

/**
 * 创建值映射
 * @param {number} connectionId - 连接ID
 * @param {Object} data - 值映射配置
 * @param {string} data.table_name - 表名
 * @param {string} data.column_name - 列名
 * @param {string} data.natural_value - 自然语言值
 * @param {string} data.db_value - 数据库实际值
 * @param {string} [data.description] - 描述说明
 * @returns {Promise<{status: string, data: Object}>}
 */
export function createValueMapping(connectionId, data) {
  return apiAdminPost(`${BASE_URL}/connections/${connectionId}/value-mappings`, data)
}

/**
 * 批量创建值映射
 * @param {number} connectionId - 连接ID
 * @param {Array} mappings - 值映射数组
 * @returns {Promise<{status: string, data: Array}>}
 */
export function batchCreateValueMappings(connectionId, mappings) {
  return apiAdminPost(`${BASE_URL}/connections/${connectionId}/value-mappings/batch`, { mappings })
}

/**
 * 删除值映射
 * @param {number} mappingId - 值映射ID
 * @returns {Promise<{status: string, message: string}>}
 */
export function deleteValueMapping(mappingId) {
  return apiAdminDelete(`${BASE_URL}/value-mappings/${mappingId}`)
}

// =============================================================================
// === Skills 管理 ===
// =============================================================================

/**
 * 生成报表技能草稿
 * @param {number} connectionId - 连接ID
 * @param {Object} data - 技能生成参数
 * @param {string} data.business_scenario - 业务场景
 * @param {Array<string>} [data.target_metrics] - 目标指标
 * @param {Array<string>} [data.constraints] - 约束条件
 * @returns {Promise<{status: string, data: Object}>}
 */
export function generateReporterSkill(connectionId, data) {
  return apiAdminPost(`${BASE_URL}/connections/${connectionId}/skills/generate`, data)
}

/**
 * 获取连接下技能列表
 * @param {number} connectionId - 连接ID
 * @returns {Promise<{status: string, data: Array}>}
 */
export function listReporterSkills(connectionId) {
  return apiAdminGet(`${BASE_URL}/connections/${connectionId}/skills`)
}

/**
 * 发布技能
 * @param {number} connectionId - 连接ID
 * @param {string} skillId - 技能ID
 * @returns {Promise<{status: string, data: Object}>}
 */
export function publishReporterSkill(connectionId, skillId) {
  return apiAdminPost(`${BASE_URL}/connections/${connectionId}/skills/${skillId}/publish`)
}
