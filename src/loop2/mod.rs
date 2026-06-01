use std::collections::BTreeMap;

use chrono::Utc;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrgState {
    pub org_id: String,
    pub name: String,
    #[serde(default)]
    pub users: BTreeMap<String, OrgUser>,
    #[serde(default)]
    pub projects: BTreeMap<String, ProjectSpaceState>,
}

impl OrgState {
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            org_id: format!("org_{}", Uuid::new_v4().simple()),
            name: name.into(),
            users: BTreeMap::new(),
            projects: BTreeMap::new(),
        }
    }

    pub fn add_user(&mut self, user: OrgUser) {
        self.users.insert(user.user_id.clone(), user);
    }

    pub fn add_project(&mut self, project: ProjectSpaceState) {
        self.projects.insert(project.project_id.clone(), project);
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrgUser {
    pub user_id: String,
    pub display_name: String,
    #[serde(default)]
    pub roles: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectSpaceState {
    pub project_id: String,
    pub name: String,
    #[serde(default)]
    pub participants: BTreeMap<String, ProjectRole>,
    #[serde(default)]
    pub tasks: BTreeMap<String, ProjectTask>,
    pub created_at: chrono::DateTime<chrono::Utc>,
}

impl ProjectSpaceState {
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            project_id: format!("proj_{}", Uuid::new_v4().simple()),
            name: name.into(),
            participants: BTreeMap::new(),
            tasks: BTreeMap::new(),
            created_at: Utc::now(),
        }
    }

    pub fn add_participant(&mut self, user_id: impl Into<String>, role: ProjectRole) {
        self.participants.insert(user_id.into(), role);
    }

    pub fn add_task(&mut self, task: ProjectTask) {
        self.tasks.insert(task.task_id.clone(), task);
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum ProjectRole {
    Owner,
    Maintainer,
    Contributor,
    Viewer,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum RuntimeStatus {
    Starting,
    Running,
    Draining,
    Stopped,
    Failed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuntimeRef {
    pub runtime_id: String,
    pub user_id: String,
    pub status: RuntimeStatus,
    pub lease_until: Option<chrono::DateTime<chrono::Utc>>,
    #[serde(default)]
    pub metadata: BTreeMap<String, Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectTask {
    pub task_id: String,
    pub title: String,
    pub assignee_user_id: Option<String>,
    #[serde(default)]
    pub depends_on: Vec<String>,
    #[serde(default)]
    pub metadata: BTreeMap<String, Value>,
}

impl ProjectTask {
    pub fn new(title: impl Into<String>) -> Self {
        Self {
            task_id: format!("task_{}", Uuid::new_v4().simple()),
            title: title.into(),
            assignee_user_id: None,
            depends_on: Vec::new(),
            metadata: BTreeMap::new(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HandoffRequest {
    pub handoff_id: String,
    pub project_id: String,
    pub from_user_id: String,
    pub to_user_id: String,
    pub task_id: Option<String>,
    pub reason: String,
    pub created_at: chrono::DateTime<chrono::Utc>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProjectEvent {
    pub event_id: String,
    pub project_id: String,
    pub event_type: String,
    #[serde(default)]
    pub payload: BTreeMap<String, Value>,
    pub created_at: chrono::DateTime<chrono::Utc>,
}

impl ProjectEvent {
    pub fn new(project_id: impl Into<String>, event_type: impl Into<String>) -> Self {
        Self {
            event_id: format!("pevt_{}", Uuid::new_v4().simple()),
            project_id: project_id.into(),
            event_type: event_type.into(),
            payload: BTreeMap::new(),
            created_at: Utc::now(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn org_tracks_users_projects_and_tasks() {
        let mut org = OrgState::new("loops");
        org.add_user(OrgUser {
            user_id: "user-a".to_string(),
            display_name: "User A".to_string(),
            roles: vec!["admin".to_string()],
        });
        let mut project = ProjectSpaceState::new("migration");
        project.add_participant("user-a", ProjectRole::Owner);
        let task = ProjectTask::new("port loop0");
        let task_id = task.task_id.clone();
        project.add_task(task);
        let project_id = project.project_id.clone();
        org.add_project(project);

        assert!(org.users.contains_key("user-a"));
        assert_eq!(
            org.projects[&project_id].participants["user-a"],
            ProjectRole::Owner
        );
        assert!(org.projects[&project_id].tasks.contains_key(&task_id));
    }
}
