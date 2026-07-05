# Workspace Guidelines

This repository is a Home Assistant Community Store (HACS) custom integration. When developing, modifying, or testing code in this project, you must adhere to the guidelines below.

## Repository & HACS Structure Guidelines
- **Directory Layout**: All integration code must be under `custom_components/<domain>/` (e.g., `custom_components/amtrak_tracker/`). Do not put files outside this directory unless they are repository-level configurations.
- **HACS Manifest (`hacs.json`)**: Must exist in the root of the repository. Ensure keys like `name`, `homeassistant` (minimum HA version), `hacs` (minimum HACS version), and `domains` are correct. Set `"render_readme": true` to display `README.md` on the HACS portal.
- **README Updates**: The `README.md` must be updated if there have been changes or additions to the core functionality of the integration.
- **Home Assistant Manifest (`manifest.json`)**: Located inside the domain folder. It must include the following keys:
  - `domain`: The unique identifier of the integration.
  - `name`: Human-readable name.
  - `codeowners`: GitHub handles of maintainers.
  - `version`: Version string (must match HACS release tags).
  - `iot_class`: The IoT class (e.g., `local_polling`, `cloud_polling`).
  - `documentation` and `issue_tracker` URLs.

## Integration Development Best Practices
- **Asynchronous Execution**:
  - Do not use blocking I/O (e.g., `requests`, standard `urllib`, blocking file reads/writes) in async methods.
  - Use `aiohttp` (via `async_get_clientsession(hass)`) for API calls.
  - If a library performs blocking operations, run it in the executor using `await hass.async_add_executor_job(func, *args)`.
- **Config Flow**:
  - Always support configuration via a UI Config Flow (`config_flow.py`). Hardcoded YAML configurations are deprecated in Home Assistant.
  - Implement a `DataUpdateCoordinator` (`coordinator.py`) to manage polling data from external sources and sharing it across multiple entities.
  - Ensure configuration updates and migrations are compatible with previous versions.
- **Strings and Localization**:
  - Maintain user-facing text and translations inside `strings.json` and the `translations/` directory.

## Testing Guidelines
- **Test Structure**:
  - Place tests in the `tests/` directory at the repository root. Do not put test files inside `custom_components/`.
- **Pytest Plugin**:
  - Use `pytest-homeassistant-custom-component` to run tests and mock Home Assistant components.
  - Maintain `tests/conftest.py` with an autouse fixture to enable custom integrations:
    ```python
    @pytest.fixture(autouse=True)
    def auto_enable_custom_integrations():
        with mock.patch("homeassistant.loader.async_get_custom_components", return_value={}):
            yield
    ```
- **Code Quality**:
  - Run linting and formatting via `ruff`, `pylint`, or `mypy` to match Home Assistant standards.

## Commit Message Guidelines
All commits in this repository must follow the **Conventional Commits** specification.
Format: `<type>(<optional scope>): <description>`

Common types:
- `feat`: A new feature
- `fix`: A bug fix
- `docs`: Documentation only changes
- `style`: Changes that do not affect the meaning of the code (white-space, formatting, missing semi-colons, etc.)
- `refactor`: A code change that neither fixes a bug nor adds a feature
- `perf`: A code change that improves performance
- `test`: Adding missing tests or correcting existing tests
- `chore`: Changes to the build process or auxiliary tools and libraries such as documentation generation

Example:
`feat(sensor): add train station schedule tracking`

## Pull Request & Branching Guidelines
- **Branching Strategy**: Always develop, modify, or test code in a dedicated feature branch. Do not push changes directly to the `main` branch.
- **PR Integration**: Pull requests must be squash-merged into the `main` branch to enforce a clean, linear history (enforced via branch protection rules). Head branches are configured to be automatically deleted upon merge.
- **PR Titles**: Since the repository is configured to use the Pull Request title as the squash commit message, the PR title must follow the **Conventional Commits** specification (e.g., `feat(sensor): add train station schedule tracking`).
- **PR Body**: The pull request body must follow a structured format with `### Summary` and `### Details` (covering **Problem**, **Solution**, and **Testing**).
  Example format:
  ```markdown
  ### Summary
  [Brief description of what the PR accomplishes and high-level context]

  ### Details
  - **Problem:** [Describe the issue, bug, or why the feature is needed]
  - **Solution:** [Explain the implementation details and how the code is changed to resolve the problem]
  - **Testing:** [Detail the automated and manual verification done, ensuring unit tests pass]
  ```
- **Required Checks**: Ensure all status checks (e.g., tests, linting, validation) pass before merging.

