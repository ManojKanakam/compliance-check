import streamlit as st
import requests
import re

# === 🔐 GitLab Setup ===
API_TOKEN = st.secrets["GITLAB_API_TOKEN"]
GITLAB_URL = "https://code.swecha.org"
API_URL = f"{GITLAB_URL}/api/v4"
REQUIRED_FILES = [
    "README.md",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "LICENSE",
]
# Files that can exist without .md extension (for CHANGELOG)
FLEXIBLE_EXTENSION_FILES = [
    "CHANGELOG"
]
# Enhanced template matching patterns
ISSUE_TEMPLATE_PATTERNS = [
    r"issue.*template.*\.md$",
    r"issue.*templates.*\.md$",
    r"issuetemplate.*\.md$",
    r"issuetemplates.*\.md$"
]
MR_TEMPLATE_PATTERNS = [
    r"merge.*request.*template.*\.md$",
    r"merge.*request.*templates.*\.md$",
    r"mr.*template.*\.md$",
    r"mr.*templates.*\.md$",
    r"mergerequesttemplate.*\.md$",
    r"mergerequesttemplates.*\.md$"
]

# === Helper Functions ===
def get_headers():
    return {"PRIVATE-TOKEN": API_TOKEN}

def file_exists(project_id, file_path):
    url = f"{API_URL}/projects/{project_id}/repository/files/{requests.utils.quote(file_path, safe='')}"
    for branch in ['master', 'main']:
        res = requests.get(url, headers=get_headers(), params={"ref": branch})
        if res.status_code == 200:
            return True
    return False

def file_exists_flexible(project_id, file_path):
    """
    Check if file exists with or without .md extension for flexible files
    Returns True if file exists in any supported format
    """
    if file_exists(project_id, file_path):
        return True
    base_name = file_path.replace('.md', '')
    if base_name in FLEXIBLE_EXTENSION_FILES:
        if file_exists(project_id, base_name):
            return True
        variations = [
            base_name.upper(),
            base_name.lower(),
            f"{base_name}.txt",
            f"{base_name.upper()}.txt",
            f"{base_name.lower()}.txt",
            f"{base_name}.rst",
            f"{base_name.upper()}.rst",
            f"{base_name.lower()}.rst"
        ]
        for variation in variations:
            if file_exists(project_id, variation):
                return True
    return False

def match_template_patterns(filename, patterns):
    """
    Check if filename matches any of the template patterns (case-insensitive)
    Only matches files that end with .md
    """
    if not filename.lower().endswith('.md'):
        return False
    filename_lower = filename.lower()
    for pattern in patterns:
        if re.match(pattern, filename_lower, re.IGNORECASE):
            return True
    return False

def directory_contains_templates(project_id, template_patterns):
    """
    Check for any .md file in .gitlab/ directory (or subdirs) matching the given patterns
    """
    tree_url = f"{API_URL}/projects/{project_id}/repository/tree"
    params = {"path": ".gitlab", "recursive": True, "per_page": 100}
    res = requests.get(tree_url, headers=get_headers(), params=params)
    if res.status_code != 200:
        return False
    files = [f["name"] for f in res.json() if f["type"] == "blob"]
    for filename in files:
        if match_template_patterns(filename, template_patterns):
            return True
    return False

def has_profile_readme(username):
    url = f"{API_URL}/projects/{username}%2F{username}"
    res = requests.get(url, headers=get_headers())
    if res.status_code != 200:
        return False, None
    project_id = res.json().get("id")
    readme_exists = file_exists(project_id, "README.md")
    readme_url = None
    if readme_exists:
        if file_exists_with_branch(project_id, "README.md", "main"):
            readme_url = f"{GITLAB_URL}/{username}/{username}/-/blob/main/README.md"
        elif file_exists_with_branch(project_id, "README.md", "master"):
            readme_url = f"{GITLAB_URL}/{username}/{username}/-/blob/master/README.md"
    return readme_exists, readme_url

def file_exists_with_branch(project_id, file_path, branch):
    """Helper function to check if file exists in specific branch"""
    url = f"{API_URL}/projects/{project_id}/repository/files/{requests.utils.quote(file_path, safe='')}"
    res = requests.get(url, headers=get_headers(), params={"ref": branch})
    return res.status_code == 200

def get_all_projects_with_pagination(params):
    """
    Fetch all projects using pagination to get complete list
    """
    all_projects = []
    page = 1
    per_page = 100
    while True:
        current_params = params.copy()
        current_params.update({
            "page": page,
            "per_page": per_page
        })
        projects_url = f"{API_URL}/projects"
        res = requests.get(projects_url, headers=get_headers(), params=current_params)
        if res.status_code != 200:
            break
        projects = res.json()
        if not projects:
            break
        all_projects.extend(projects)
        if len(projects) < per_page:
            break
        page += 1
        if page > 1000:
            st.warning("⚠️ Reached pagination limit. Some projects might not be displayed.")
            break
    return all_projects

def get_contributed_projects(username):
    user_resp = requests.get(f"{API_URL}/users?username={username}", headers=get_headers())
    if user_resp.status_code != 200 or not user_resp.json():
        return []
    user_id = user_resp.json()[0]['id']
    params = {
        "membership": True,
        "order_by": "last_activity_at"
    }
    return get_all_projects_with_pagination(params)

def get_project_by_id_or_url(project_input):
    if project_input.isdigit():
        res = requests.get(f"{API_URL}/projects/{project_input}", headers=get_headers())
        return res.json() if res.status_code == 200 else None
    elif GITLAB_URL in project_input:
        path = project_input.replace(f"{GITLAB_URL}/", "").split("/-/")[0]
        encoded = requests.utils.quote(path, safe="")
        res = requests.get(f"{API_URL}/projects/{encoded}", headers=get_headers())
        if res.status_code == 200:
            return res.json()
    return None

def determine_input_type_and_process(input_value):
    """
    Determine the type of input and return appropriate:
    - ('project', project_data) for project_id or project_url
    - ('projects', [project_list]) for username
    - ('error', message) otherwise

    Note: User ID lookup is disabled to avoid conflict with project IDs.
    """
    input_value = input_value.strip()

    # Check for project URL
    if GITLAB_URL in input_value:
        project = get_project_by_id_or_url(input_value)
        if project:
            return ('project', project)
        else:
            return ('error', "Could not fetch project from the provided URL")

    # Numeric input → treated ONLY as Project ID (not user ID)
    elif input_value.isdigit():
        project = get_project_by_id_or_url(input_value)
        if project:
            return ('project', project)
        else:
            return ('error', f"No project found with ID: {input_value}")

    # Otherwise, treat as username
    else:
        projects = get_contributed_projects(input_value)
        if projects:
            return ('projects', projects)
        else:
            return ('error', f"No projects found for username: {input_value}")

def get_compliance_status(project_id):
    status = {}
    for file in REQUIRED_FILES:
        if file.replace('.md', '') in FLEXIBLE_EXTENSION_FILES:
            status[file] = file_exists_flexible(project_id, file)
        else:
            status[file] = file_exists(project_id, file)
    status[".gitlab/issue_templates"] = directory_contains_templates(project_id, ISSUE_TEMPLATE_PATTERNS)
    status[".gitlab/merge_request_templates"] = directory_contains_templates(project_id, MR_TEMPLATE_PATTERNS)
    res = requests.get(f"{API_URL}/projects/{project_id}", headers=get_headers())
    if res.status_code != 200:
        return {}
    project = res.json()
    status['description_present'] = bool(project.get("description"))
    status['tags_present'] = bool(project.get("tag_list")) and len(project.get("tag_list")) > 0
    return status

def get_project_url(project_data):
    """Generate the web URL for the project"""
    return project_data.get('web_url', f"{GITLAB_URL}/{project_data.get('path_with_namespace', '')}")

# === 🎯 UI ===
st.set_page_config(page_title="GitLab Self-Check App", layout="wide")
st.sidebar.title("🔍 GitLab Checker")
choice = st.sidebar.radio("Choose a function", ["Check Profile README", "Project Compliance Check"])
st.title("🧪 GitLab Self-Check App")

# === 1. Check Profile README ===
if choice == "Check Profile README":
    st.subheader("✅ Profile README Check")
    username = st.text_input("Enter GitLab Username (case-sensitive)")
    if st.button("Check README"):
        if not username:
            st.warning("Please enter a username.")
        else:
            readme_exists, readme_url = has_profile_readme(username)
            if readme_exists:
                st.success("✅ README.md is present in the profile repo.")
                if readme_url:
                    st.markdown(f"[🔗 View README]({readme_url})")
            else:
                st.error("❌ README.md is missing in the profile repo.")

# === 2. Project Compliance Check ===
elif choice == "Project Compliance Check":
    st.subheader("📊 Project Compliance Check")
    st.markdown("**Enter:** Username, Project ID, or Project URL")
    input_value = st.text_input("", key="unified_input", placeholder="e.g., john_doe, 12345, or https://code.swecha.org/group/project")
    selected_project = None
    projects_list = None

    if input_value:
        with st.spinner('🔍 Analyzing input and fetching data...'):
            input_type, data = determine_input_type_and_process(input_value)

        if input_type == 'error':
            st.error(f"❌ {data}")
        elif input_type == 'project':
            selected_project = data
            st.success(f"✅ Found project: {selected_project['name_with_namespace']}")
        elif input_type == 'projects':
            projects_list = data
            if not projects_list:
                st.warning("No projects found for this user.")
            else:
                st.success(f"✅ Found {len(projects_list)} projects for this user")
                if len(projects_list) > 100:
                    st.info(f"📊 Fetched all {len(projects_list)} projects (using pagination)")
                project_names = [f"{p['name_with_namespace']} ({p['id']})" for p in projects_list]
                selected = st.selectbox("Select a project to check compliance", project_names)
                selected_project = next(p for p in projects_list if f"{p['name_with_namespace']} ({p['id']})" == selected)

    if selected_project and st.button("Check Compliance"):
        project_id = selected_project["id"]
        project_url = get_project_url(selected_project)
        status = get_compliance_status(project_id)
        if not status:
            st.error("Failed to fetch compliance info.")
        else:
            st.markdown("### 🔗 Project Information")
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**📁 Project:** `{selected_project.get('name_with_namespace', 'Unknown')}`")
            with col2:
                st.markdown(f"[🔗 **View Repository**]({project_url})")

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("⭐ Stars", selected_project.get('star_count', 0))
            with col2:
                st.metric("🍴 Forks", selected_project.get('forks_count', 0))
            with col3:
                st.metric("📅 Last Activity", selected_project.get('last_activity_at', 'Unknown')[:10])

            st.markdown("---")
            score = sum(1 for present in status.values() if present)
            total = len(status)
            progress_percentage = score / total

            st.markdown("### 📊 Compliance Score")
            col1, col2 = st.columns([3, 1])
            with col1:
                st.progress(progress_percentage)
            with col2:
                color = "🟢" if score == total else "🟡" if score >= total * 0.7 else "🔴"
                st.markdown(f"### {color} {score}/{total}")

            if score == total:
                st.success("🎉 **Excellent!** Your project meets all compliance requirements!")
            elif score >= total * 0.8:
                st.info("👍 **Good!** Your project meets most compliance requirements.")
            elif score >= total * 0.6:
                st.warning("⚠️ **Needs Improvement** - Several requirements are missing.")
            else:
                st.error("❌ **Poor Compliance** - Many important files are missing.")

            st.markdown("---")

            # Styled Detailed Compliance Check
            st.markdown("### 📋 Detailed Compliance Check")
            st.markdown("""
                <style>
                .compliance-container {
                    background-color: #f0f7ff;
                    padding: 16px;
                    border-radius: 8px;
                    border-left: 5px solid #357edd;
                }
                .compliance-category {
                    font-weight: bold;
                    color: #0a4d8c;
                    margin-top: 10px;
                    margin-bottom: 6px;
                }
                </style>
            """, unsafe_allow_html=True)
            st.markdown('<div class="compliance-container">', unsafe_allow_html=True)

            file_items = {k: v for k, v in status.items() if k in REQUIRED_FILES or k == "CHANGELOG.md"}
            template_items = {k: v for k, v in status.items() if ".gitlab/" in k}
            metadata_items = {k: v for k, v in status.items() if "present" in k}

            if file_items:
                st.markdown('<p class="compliance-category">📄 Required Files</p>', unsafe_allow_html=True)
                for item, present in file_items.items():
                    emoji = "✅" if present else "❌"
                    display_name = item.replace('_', ' ').replace('.md', '.md')
                    if present:
                        st.markdown(f"{emoji} **{display_name}**")
                    else:
                        st.markdown(f"{emoji} **{display_name}**")

            if template_items:
                st.markdown('<p class="compliance-category">📝 GitLab Templates</p>', unsafe_allow_html=True)
                for item, present in template_items.items():
                    emoji = "✅" if present else "❌"
                    display_name = item.replace('_', ' ').replace('.gitlab/', '').title()
                    if present:
                        st.markdown(f"{emoji} **{display_name}**")
                    else:
                        st.markdown(f"{emoji} **{display_name}**")

            if metadata_items:
                st.markdown('<p class="compliance-category">ℹ️ Project Metadata</p>', unsafe_allow_html=True)
                for item, present in metadata_items.items():
                    emoji = "✅" if present else "❌"
                    display_name = item.replace('_', ' ').title()
                    if present:
                        st.markdown(f"{emoji} **{display_name}**")
                    else:
                        st.markdown(f"{emoji} **{display_name}**")

            st.markdown('</div>', unsafe_allow_html=True)

    elif not input_value:
        st.info("💡 Enter a username, project ID, or project URL above to get started.")