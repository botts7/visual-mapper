# Contributing to Visual Mapper

**Purpose:** Guidelines for contributing to Visual Mapper.

**Starting Version:** 1.0.0 (Phase 7)
**Last Updated:** 2025-12-21

---

## 🎯 How to Contribute

**Types of contributions:**
1. Bug reports
2. Feature requests
3. Code contributions
4. Documentation improvements
5. Plugin development

---

## 🐛 Bug Reports

**Before submitting:**
- Check existing issues
- Verify it's not already fixed
- Test in latest version

**Include in report:**
- Visual Mapper version
- Home Assistant version
- Android device model/version
- Steps to reproduce
- Expected vs actual behavior
- Console errors (F12 in browser)

---

## 💡 Feature Requests

**Good feature requests:**
- Clearly describe the problem
- Explain the proposed solution
- Consider alternatives
- Show examples/mockups

---

## 🔧 Code Contributions

### **Development Workflow**

1. Fork the repository
2. Create feature branch: `git checkout -b feature/my-feature`
3. Read [NEW_PROJECT_PLAN.md](NEW_PROJECT_PLAN.md) to understand current phase
4. Write tests FIRST (TDD)
5. Implement feature following patterns in files 20-25
6. Ensure all tests pass
7. Update documentation
8. Submit pull request

### **Code Standards**

**JavaScript:**
- ES6 modules with dual export
- Cache busting on imports
- DOM ready checks
- Null safety
- Error handling

**Python:**
- PEP 8 style
- Type hints
- Async/await for I/O
- Error handling

**See:** [60_SOLID_PRINCIPLES.md](60_SOLID_PRINCIPLES.md) for architecture guidance

### **Testing Requirements**

**All PRs must include:**
- Unit tests (Jest/pytest)
- Integration tests if applicable
- E2E tests for user-facing features
- Coverage >60%

**See:** [41_TESTING_PLAYWRIGHT.md](41_TESTING_PLAYWRIGHT.md) and [42_TESTING_JEST_PYTEST.md](42_TESTING_JEST_PYTEST.md)

---

## 📝 Documentation

**Update documentation when:**
- Adding new features
- Changing existing behavior
- Fixing bugs
- Adding examples

**Documentation files:** See [00_START_HERE.md](00_START_HERE.md)

---

## 🔌 Plugin Development

**Coming in Phase 7 (v1.0.0):**
- Plugin architecture
- Example plugins
- Plugin API documentation

---

## ✅ Pull Request Checklist

Before submitting PR:

- [ ] Tests written and passing
- [ ] Code follows style guidelines
- [ ] Documentation updated
- [ ] No console errors
- [ ] Cache busting applied
- [ ] Null safety checks added
- [ ] No breaking changes (or clearly documented)
- [ ] PR description explains what/why

---

## 🎓 Resources

**Documentation:**
- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) - Project context
- [NEW_PROJECT_PLAN.md](NEW_PROJECT_PLAN.md) - Build plan
- [10_SYSTEM_ARCHITECTURE.md](10_SYSTEM_ARCHITECTURE.md) - Architecture
- Files 20-25 - Code patterns

**Getting Help:**
- GitHub Issues
- GitHub Discussions
- Documentation

---

## 📜 License

Visual Mapper is open-source under MIT License.

By contributing, you agree to license your contributions under the same license.

---

## 🙏 Thank You!

Thank you for contributing to Visual Mapper!

Every contribution, big or small, helps make this project better for the Home Assistant community.

---

**Document Version:** 1.0.0
**Created:** 2025-12-21
**Target Version:** Visual Mapper 1.0.0+
