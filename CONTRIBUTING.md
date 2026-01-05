# Contributing to Visual Mapper

Thank you for your interest in contributing to Visual Mapper!

## Quick Start

1. **Fork** the repository
2. **Clone** your fork: `git clone https://github.com/YOUR_USERNAME/visual-mapper.git`
3. **Create a branch**: `git checkout -b feature/my-feature`
4. **Make changes** and write tests
5. **Run tests**: `python -m pytest tests/ -v`
6. **Submit** a pull request

## What We're Looking For

- Bug fixes
- New features
- Documentation improvements
- Test coverage improvements
- Performance optimizations

## Code Standards

- **Python**: PEP 8, type hints, async/await for I/O
- **JavaScript**: ES6 modules, dual export pattern
- **Kotlin**: Android best practices, null safety

## Testing Requirements

All PRs must include tests:
```bash
# Run all tests
python -m pytest tests/ -v

# Run with coverage
python -m pytest tests/ -v --cov=.
```

## PR Checklist

- [ ] Tests pass
- [ ] No console errors
- [ ] Documentation updated (if applicable)
- [ ] PR description explains changes

## Need Help?

- Read the [detailed contributing guide](docs/architecture/61_CONTRIBUTING.md)
- Open an [issue](https://github.com/YOUR_USERNAME/visual-mapper/issues)
- Start a [discussion](https://github.com/YOUR_USERNAME/visual-mapper/discussions)

## License

By contributing, you agree to license your contributions under the MIT License.
