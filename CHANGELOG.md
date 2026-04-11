# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- GitHub Actions CI/CD pipeline with automated testing, linting, and deployment
- Comprehensive test suite for `fetch_news` and database models
- Modern Python project configuration with `pyproject.toml`
- Pre-commit hooks for code quality checks (black, isort, flake8, mypy, bandit)
- Code coverage reporting with pytest-cov
- Enhanced `.gitignore` for development environments
- Development dependencies separation
- Health check endpoint at `/health`

### Changed
- Updated README.md with detailed development and contribution guidelines
- Improved project structure and documentation
- Enhanced error handling and logging

### Fixed
- Various code quality issues identified by linters
- Test environment configuration

## [1.0.0] - 2024-04-10

### Added
- Initial release of Political News System
- Automated news fetching from Chinese government websites
- Monthly archiving and organization of political content
- Responsive web interface with modern design
- RESTful API endpoints for programmatic access
- Background synchronization with batch backfill support
- Docker and Docker Compose deployment configurations
- Comprehensive documentation and deployment scripts
- Support for SQLite, PostgreSQL, and MySQL databases
- Scheduled automatic synchronization

### Features
- Today's and yesterday's political news display
- Year-based filtering and navigation
- Progress reporting for background tasks
- Error handling and recovery mechanisms
- Environment-based configuration
- Health checks and monitoring

## Versioning

This project uses [Semantic Versioning](http://semver.org/). Given a version number MAJOR.MINOR.PATCH:

- **MAJOR** version for incompatible API changes
- **MINOR** version for new functionality in a backward-compatible manner
- **PATCH** version for backward-compatible bug fixes

## Release Process

1. Update version in `pyproject.toml`
2. Update this CHANGELOG.md with release notes
3. Create a git tag: `git tag -a v1.0.0 -m "Release v1.0.0"`
4. Push the tag: `git push origin v1.0.0`
5. GitHub Actions will automatically build and deploy

## Contributing

Please see [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
