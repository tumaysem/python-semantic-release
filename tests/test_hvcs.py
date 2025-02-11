import base64
import json
import os
import platform
from tempfile import NamedTemporaryFile
from unittest import TestCase, mock

import pytest
import responses

from semantic_release.errors import ImproperConfigurationError
from semantic_release.hvcs import (
    Gitea,
    Github,
    Gitlab,
    check_build_status,
    check_token,
    get_hvcs,
    post_changelog,
)

from . import mock, wrapped_config_get
from .mocks.mock_gitlab import mock_gitlab

temp_dir = (
    os.path.join(os.path.abspath(os.path.dirname(__file__)), "tmp")
    if platform.system() == "Windows"
    else "/tmp/"
)


@mock.patch("semantic_release.hvcs.config.get", wrapped_config_get(hvcs="github"))
def test_get_hvcs_should_return_github():
    assert get_hvcs() == Github


@mock.patch("semantic_release.hvcs.config.get", wrapped_config_get(hvcs="gitlab"))
def test_get_hvcs_should_return_gitlab():
    assert get_hvcs() == Gitlab


@mock.patch("semantic_release.hvcs.config.get", wrapped_config_get(hvcs="gitea"))
def test_get_hvcs_should_return_gitea():
    assert get_hvcs() == Gitea


@mock.patch("semantic_release.hvcs.config.get", lambda *x: "doesnotexist")
def test_get_hvcs_should_raise_improper_config():
    pytest.raises(ImproperConfigurationError, get_hvcs)


@mock.patch("semantic_release.hvcs.Github.check_build_status")
def test_check_build_status(mock_github_helper):
    check_build_status("owner", "name", "ref")
    mock_github_helper.assert_called_once_with("owner", "name", "ref")


@mock.patch("os.environ", {"GH_TOKEN": "token"})
def test_check_token_should_return_true():
    assert check_token() is True


@mock.patch("os.environ", {})
def test_check_token_should_return_false():
    assert check_token() is False


###############################
# test custom token variables #
###############################
@mock.patch("os.environ", {"CUSTOM_GH_TOKEN": "token"})
@mock.patch(
    "semantic_release.hvcs.config.get",
    wrapped_config_get(github_token_var="CUSTOM_GH_TOKEN"),
)
def test_check_custom_github_token_var_should_return_true():
    assert check_token() is True


@mock.patch("os.environ", {"GH_TOKEN": "token"})
@mock.patch(
    "semantic_release.hvcs.config.get",
    wrapped_config_get(github_token_var="CUSTOM_TOKEN"),
)
def test_check_custom_github_token_should_return_false():
    assert check_token() is False


@mock.patch("os.environ", {"GITEA_TOKEN": "token"})
@mock.patch(
    "semantic_release.hvcs.config.get",
    wrapped_config_get(gitea_token_var="CUSTOM_TOKEN"),
)
def test_check_custom_gitea_token_should_return_false():
    assert check_token() is False


@mock.patch("os.environ", {"GITEA_CUSTOM_TOKEN": "token"})
@mock.patch(
    "semantic_release.hvcs.config.get",
    wrapped_config_get(gitea_token_var="GITEA_CUSTOM_TOKEN"),
)
def test_check_custom_gitea_token_should_return_false():
    assert check_token() is False


@mock.patch("os.environ", {"CUSTOM_GL_TOKEN": "token"})
@mock.patch(
    "semantic_release.hvcs.config.get",
    wrapped_config_get(github_token_var="CUSTOM_GL_TOKEN"),
)
def test_check_custom_gitlab_token_var_should_return_true():
    assert check_token() is True


@mock.patch("os.environ", {"GL_TOKEN": "token"})
@mock.patch(
    "semantic_release.hvcs.config.get",
    wrapped_config_get(gitlab_token_var="CUSTOM_TOKEN"),
)
def test_check_custom_gitlab_token_should_return_false():
    assert check_token() is False


@pytest.mark.parametrize(
    "hvcs,hvcs_domain,expected_domain,expected_api_url,ci_server_host,hvcs_api_domain",
    [
        ("github", None, "github.com", "https://api.github.com", None, None),
        ("gitlab", None, "gitlab.com", "https://gitlab.com", None, None),
        (
            "gitea",
            "git.grassrootseconomics.net",
            "git.grassrootseconomics.net",
            "https://git.grassrootseconomics.net/api/v1",
            None,
            None,
        ),
        (
            "github",
            "github.example.com",
            "github.example.com",
            "https://api.github.com",
            None,
            None,
        ),
        (
            "github",
            "github.example.com",
            "github.example.com",
            "https://api.github.enterprise",
            None,
            "api.github.enterprise",
        ),
        (
            "gitlab",
            "example.gitlab.com",
            "example.gitlab.com",
            "https://example.gitlab.com",
            None,
            None,
        ),
        (
            "gitlab",
            "example.gitlab.com/path",
            "example.gitlab.com/path",
            "https://example.gitlab.com/path",
            None,
            None,
        ),
        (
            "gitlab",
            "example2.gitlab.com",
            "example2.gitlab.com",
            "https://example2.gitlab.com",
            "ciserverhost.gitlab.com",
            None,
        ),
    ],
)
@mock.patch("os.environ", {"GL_TOKEN": "token"})
def test_get_domain_should_have_expected_domain(
    hvcs,
    hvcs_domain,
    expected_domain,
    expected_api_url,
    ci_server_host,
    hvcs_api_domain,
):
    with mock.patch(
        "semantic_release.hvcs.config.get",
        wrapped_config_get(
            hvcs_domain=hvcs_domain, hvcs=hvcs, hvcs_api_domain=hvcs_api_domain
        ),
    ):
        with mock.patch(
            "os.environ",
            {
                "GL_TOKEN": "token",
                "GH_TOKEN": "token",
                "GITEA_TOKEN": "token",
                "CI_SERVER_HOST": ci_server_host,
            },
        ):
            assert get_hvcs().domain() == expected_domain
            assert get_hvcs().api_url() == expected_api_url


@responses.activate
@pytest.mark.parametrize(
    "hvcs,url,prerelease",
    [
        ("github", "https://api.github.com/repos/relekang/rmoq/releases", True),
        ("github", "https://api.github.com/repos/relekang/rmoq/releases", False),
        ("gitea", "https://gitea.com/api/v1/repos/gitea/tea/releases", True),
        ("gitea", "https://gitea.com/api/v1/repos/gitea/tea/releases", False),
    ],
)
def test_should_create_prerelease_if_asked_for(hvcs, url, prerelease):
    with NamedTemporaryFile("w") as netrc_file:
        if hvcs == "github":
            netrc_file.write("machine api.github.com\n")
        elif hvcs == "gitea":
            netrc_file.write("machine gitea.com\n")
        netrc_file.write("login username\n")
        netrc_file.write("password password\n")

        netrc_file.flush()

        def request_callback(request):
            payload = json.loads(request.body)
            assert payload["tag_name"] == "v1.0.0"
            assert payload["body"] == "text"
            assert payload["draft"] is False
            assert payload["prerelease"] is prerelease
            auth_str = (
                "Basic "
                + base64.encodebytes(b"username:password").decode("ascii").strip()
            )
            assert auth_str == request.headers.get("Authorization")
            return 201, {}, json.dumps({})

        responses.add_callback(
            responses.POST,
            url,
            callback=request_callback,
            content_type="application/json",
        )

        with mock.patch.dict(os.environ, {"NETRC": netrc_file.name}):
            if hvcs == "github":
                status = Github.post_release_changelog(
                    "relekang", "rmoq", "1.0.0", "text", prerelease
                )
            elif hvcs == "gitea":
                status = Gitea.post_release_changelog(
                    "gitea", "tea", "1.0.0", "text", prerelease
                )
            assert status is True


@mock.patch("semantic_release.hvcs.config.get", wrapped_config_get(hvcs="github"))
@mock.patch(
    "os.environ",
    {
        "GITHUB_API_URL": "api.github.enterprise",
        "GITHUB_SERVER_URL": "github.enterprise",
    },
)
def test_ghe_domain_should_be_retrieved_from_env():
    assert get_hvcs().domain() == "github.enterprise"
    assert get_hvcs().api_url() == "https://api.github.enterprise"


@mock.patch("semantic_release.hvcs.config.get", wrapped_config_get(hvcs="gitlab"))
@mock.patch("os.environ", {"GL_TOKEN": "token"})
def test_get_token():
    assert get_hvcs().token() == "token"


class GithubCheckBuildStatusTests(TestCase):
    url = (
        "https://api.github.com/repos/relekang/rmoq/commits/"
        "6dcb09b5b57875f334f61aebed695e2e4193db5e/status"
    )

    def get_response(self, status):
        return json.dumps(
            {
                "state": status,
                "sha": "6dcb09b5b57875f334f61aebed695e2e4193db5e",
                "total_count": 2,
            }
        )

    @responses.activate
    def test_should_return_false_if_pending(self):
        responses.add(
            responses.GET,
            self.url,
            body=self.get_response("pending"),
            content_type="application/json",
        )
        self.assertFalse(
            Github.check_build_status(
                "relekang", "rmoq", "6dcb09b5b57875f334f61aebed695e2e4193db5e"
            )
        )

    @responses.activate
    def test_should_return_false_if_failure(self):
        responses.add(
            responses.GET,
            self.url,
            body=self.get_response("failure"),
            content_type="application/json",
        )
        self.assertFalse(
            Github.check_build_status(
                "relekang", "rmoq", "6dcb09b5b57875f334f61aebed695e2e4193db5e"
            )
        )

    @responses.activate
    def test_should_return_true_if_success(self):
        responses.add(
            responses.GET,
            self.url,
            body=self.get_response("success"),
            content_type="application/json",
        )
        self.assertTrue(
            Github.check_build_status(
                "relekang", "rmoq", "6dcb09b5b57875f334f61aebed695e2e4193db5e"
            )
        )


class GiteaCheckBuildStatusTests(TestCase):
    url = "https://gitea.com/api/v1/repos/gitea/tea/statuses/268aa061795d53a1914b734c479b7c1f62cfd7af"

    def get_response(self, status):
        return json.dumps(
            {
                "status": status,
            }
        )

    @responses.activate
    def test_should_return_false_if_pending(self):
        responses.add(
            responses.GET,
            self.url,
            body=self.get_response("pending"),
            content_type="application/json",
        )
        self.assertFalse(
            Gitea.check_build_status(
                "gitea", "tea", "268aa061795d53a1914b734c479b7c1f62cfd7af"
            )
        )

    @responses.activate
    def test_should_return_false_if_failure(self):
        responses.add(
            responses.GET,
            self.url,
            body=self.get_response("failure"),
            content_type="application/json",
        )
        self.assertFalse(
            Gitea.check_build_status(
                "gitea", "tea", "268aa061795d53a1914b734c479b7c1f62cfd7af"
            )
        )

    @responses.activate
    def test_should_return_true_if_success(self):
        responses.add(
            responses.GET,
            self.url,
            body=self.get_response("success"),
            content_type="application/json",
        )
        self.assertTrue(
            Gitea.check_build_status(
                "gitea", "tea", "268aa061795d53a1914b734c479b7c1f62cfd7af"
            )
        )


class GitlabCheckBuildStatusTests(TestCase):
    @mock_gitlab("pending")
    def test_should_return_false_if_pending(self, mock_auth, mock_project):
        self.assertFalse(check_build_status("owner", "repo", "my_ref"))

    @mock_gitlab("failure")
    def test_should_return_false_if_failure(self, mock_auth, mock_project):
        self.assertFalse(check_build_status("owner", "repo", "my_ref"))

    @mock_gitlab("allow_failure")
    def test_should_return_true_if_allow_failure(self, mock_auth, mock_project):
        self.assertTrue(check_build_status("owner", "repo", "my_ref"))

    @mock_gitlab("success")
    def test_should_return_true_if_success(self, mock_auth, mock_project):
        self.assertTrue(check_build_status("owner", "repo", "my_ref"))


class GithubReleaseTests(TestCase):
    url = "https://api.github.com/repos/relekang/rmoq/releases"
    edit_url = "https://api.github.com/repos/relekang/rmoq/releases/1"
    get_url = "https://api.github.com/repos/relekang/rmoq/releases/tags/v1.0.0"
    asset_url = "https://uploads.github.com/repos/relekang/rmoq/releases/1/assets"
    asset_url_params = (
        "https://uploads.github.com/repos/relekang/rmoq/releases/1/assets"
        "?name=testupload.md&label=Dummy+file"
    )
    asset_no_extension_url_params = (
        "https://uploads.github.com/repos/relekang/rmoq/releases/1/assets"
        "?name=testupload-no-extension&label=Dummy+file+no+extension"
    )
    dist_asset_url_params = (
        "https://uploads.github.com/repos/relekang/rmoq/releases/1/assets"
        "?name=testupload.md"
    )
    upload_url = (
        "https://uploads.github.com/repos/relekang/rmoq/releases/1/assets{?name,label}"
    )

    @responses.activate
    @mock.patch("semantic_release.hvcs.Github.token", return_value="super-token")
    def test_should_post_changelog_using_github_token(self, mock_token):
        with NamedTemporaryFile("w") as netrc_file:
            netrc_file.write("machine api.github.com\n")
            netrc_file.write("login username\n")
            netrc_file.write("password password\n")

            netrc_file.flush()

            def request_callback(request):
                payload = json.loads(request.body)
                self.assertEqual(payload["tag_name"], "v1.0.0")
                self.assertEqual(payload["body"], "text")
                self.assertEqual(payload["draft"], False)
                self.assertEqual(payload["prerelease"], False)
                self.assertEqual(
                    "token super-token", request.headers.get("Authorization")
                )

                return 201, {}, json.dumps({})

            responses.add_callback(
                responses.POST,
                self.url,
                callback=request_callback,
                content_type="application/json",
            )

            with mock.patch.dict(os.environ, {"NETRC": netrc_file.name}):
                status = Github.post_release_changelog(
                    "relekang", "rmoq", "1.0.0", "text", False
                )
                self.assertTrue(status)

    @responses.activate
    @mock.patch("semantic_release.hvcs.Github.token", return_value=None)
    def test_should_post_changelog_using_netrc(self, mock_token):
        with NamedTemporaryFile("w") as netrc_file:
            netrc_file.write("machine api.github.com\n")
            netrc_file.write("login username\n")
            netrc_file.write("password password\n")

            netrc_file.flush()

            def request_callback(request):
                payload = json.loads(request.body)
                self.assertEqual(payload["tag_name"], "v1.0.0")
                self.assertEqual(payload["body"], "text")
                self.assertEqual(payload["draft"], False)
                self.assertEqual(payload["prerelease"], False)
                self.assertEqual(
                    "Basic "
                    + base64.encodebytes(b"username:password").decode("ascii").strip(),
                    request.headers.get("Authorization"),
                )

                return 201, {}, json.dumps({})

            responses.add_callback(
                responses.POST,
                self.url,
                callback=request_callback,
                content_type="application/json",
            )

            with mock.patch.dict(os.environ, {"NETRC": netrc_file.name}):
                status = Github.post_release_changelog(
                    "relekang", "rmoq", "1.0.0", "text", False
                )
                self.assertTrue(status)

    @responses.activate
    def test_should_return_false_status_if_it_failed(self):
        responses.add(
            responses.POST,
            self.url,
            status=400,
            body="{}",
            content_type="application/json",
        )
        responses.add(
            responses.GET,
            self.get_url,
            status=200,
            body='{"id": 1}',
            content_type="application/json",
        )
        responses.add(
            responses.POST,
            self.edit_url,
            status=400,
            body="{}",
            content_type="application/json",
        )
        self.assertFalse(
            Github.post_release_changelog("relekang", "rmoq", "1.0.0", "text", False)
        )

    @responses.activate
    @mock.patch("semantic_release.hvcs.Github.token", return_value="super-token")
    def test_should_upload_asset(self, mock_token):
        # Create temporary file to upload
        dummy_file_path = os.path.join(temp_dir, "testupload.md")
        os.makedirs(os.path.dirname(dummy_file_path), exist_ok=True)
        dummy_content = "# Test File\n\n*Dummy asset for testing uploads.*"
        with open(dummy_file_path, "w") as dummy_file:
            dummy_file.write(dummy_content)

        required_payload = {"upload_url": self.upload_url}
        responses.add(
            responses.GET,
            self.edit_url,
            status=200,
            body=json.dumps(required_payload),
            content_type="application/json",
        )

        def request_callback(request):
            self.assertEqual(request.body.decode().replace("\r\n", "\n"), dummy_content)
            self.assertEqual(request.url, self.asset_url_params)
            self.assertEqual(request.headers["Content-Type"], "text/markdown")
            self.assertEqual("token super-token", request.headers.get("Authorization"))

            return 201, {}, json.dumps({})

        responses.add_callback(
            responses.POST, self.asset_url, callback=request_callback
        )
        status = Github.upload_asset(
            "relekang", "rmoq", 1, dummy_file_path, "Dummy file"
        )
        self.assertTrue(status)

        # Remove test file
        os.remove(dummy_file_path)

    @responses.activate
    @mock.patch("semantic_release.hvcs.Github.token", return_value="super-token")
    def test_should_upload_asset_with_no_extension(self, mock_token):
        # Create temporary file to upload
        dummy_file_path = os.path.join(temp_dir, "testupload-no-extension")
        os.makedirs(os.path.dirname(dummy_file_path), exist_ok=True)
        dummy_content = (
            "# Test File with no extension\n\n*Dummy asset for testing uploads.*"
        )
        with open(dummy_file_path, "w") as dummy_file:
            dummy_file.write(dummy_content)

        required_payload = {"upload_url": self.upload_url}
        responses.add(
            responses.GET,
            self.edit_url,
            status=200,
            body=json.dumps(required_payload),
            content_type="application/json",
        )

        def request_callback(request):
            self.assertEqual(request.body.decode().replace("\r\n", "\n"), dummy_content)
            self.assertEqual(request.url, self.asset_no_extension_url_params)
            self.assertEqual(
                request.headers["Content-Type"], "application/octet-stream"
            )
            self.assertEqual("token super-token", request.headers["Authorization"])

            return 201, {}, json.dumps({})

        responses.add_callback(
            responses.POST, self.asset_url, callback=request_callback
        )
        status = Github.upload_asset(
            "relekang", "rmoq", 1, dummy_file_path, "Dummy file no extension"
        )
        self.assertTrue(status)

        # Remove test file
        os.remove(dummy_file_path)

    @responses.activate
    @mock.patch("semantic_release.hvcs.Github.token", return_value="super-token")
    def test_should_upload_dists(self, mock_token):
        # Create temporary file to upload
        dummy_file_path = os.path.join(temp_dir, "dist", "testupload.md")
        os.makedirs(os.path.dirname(dummy_file_path), exist_ok=True)
        dummy_content = "# Test File\n\n*Dummy asset for testing uploads.*"
        with open(dummy_file_path, "w") as dummy_file:
            dummy_file.write(dummy_content)

        required_payload = {"upload_url": self.upload_url}
        responses.add(
            responses.GET,
            self.edit_url,
            status=200,
            body=json.dumps(required_payload),
            content_type="application/json",
        )

        def request_callback(request):
            self.assertEqual(request.body.decode().replace("\r\n", "\n"), dummy_content)
            self.assertEqual(request.url, self.dist_asset_url_params)
            self.assertEqual(request.headers["Content-Type"], "text/markdown")
            self.assertEqual("token super-token", request.headers.get("Authorization"))

            return 201, {}, json.dumps({})

        responses.add(
            responses.GET,
            self.get_url,
            status=200,
            body='{"id": 1}',
            content_type="application/json",
        )
        responses.add_callback(
            responses.POST, self.asset_url, callback=request_callback
        )
        status = Github.upload_dists(
            "relekang", "rmoq", "1.0.0", os.path.dirname(dummy_file_path)
        )
        self.assertTrue(status)

        # Remove test file
        os.remove(dummy_file_path)


class GiteaReleaseTests(TestCase):
    url = "https://gitea.com/api/v1/repos/gitea/tea/releases"
    edit_url = "https://gitea.com/api/v1/repos/gitea/tea/releases/1"
    get_url = "https://gitea.com/api/v1/repos/gitea/tea/releases/tags/v1.0.0"
    asset_url = "https://gitea.com/api/v1/repos/gitea/tea/releases/1/assets"
    asset_url_params = (
        "https://gitea.com/api/v1/repos/gitea/tea/releases/1/assets"
        "?name=testupload.md"
    )
    asset_no_extension_url_params = (
        "https://gitea.com/api/v1/repos/gitea/tea/releases/1/assets"
        "?name=testupload-no-extension"
    )
    dist_asset_url_params = (
        "https://gitea.com/api/v1/repos/gitea/tea/releases/1/assets"
        "?name=testupload.md"
    )

    @responses.activate
    @mock.patch("semantic_release.hvcs.Gitea.token", return_value="super-token")
    def test_should_post_changelog_using_gitea_token(self, mock_token):
        with NamedTemporaryFile("w") as netrc_file:
            netrc_file.write("machine gitea.com\n")
            netrc_file.write("login username\n")
            netrc_file.write("password password\n")

            netrc_file.flush()

            def request_callback(request):
                payload = json.loads(request.body)
                self.assertEqual(payload["tag_name"], "v1.0.0")
                self.assertEqual(payload["body"], "text")
                self.assertEqual(payload["draft"], False)
                self.assertEqual(payload["prerelease"], False)
                self.assertEqual(
                    "token super-token", request.headers.get("Authorization")
                )

                return 201, {}, json.dumps({})

            responses.add_callback(
                responses.POST,
                self.url,
                callback=request_callback,
                content_type="application/json",
            )

            with mock.patch.dict(os.environ, {"NETRC": netrc_file.name}):
                status = Gitea.post_release_changelog(
                    "gitea", "tea", "1.0.0", "text", False
                )
                self.assertTrue(status)

    @responses.activate
    @mock.patch("semantic_release.hvcs.Gitea.token", return_value=None)
    def test_should_post_changelog_using_netrc(self, mock_token):
        with NamedTemporaryFile("w") as netrc_file:
            netrc_file.write("machine gitea.com\n")
            netrc_file.write("login username\n")
            netrc_file.write("password password\n")

            netrc_file.flush()

            def request_callback(request):
                payload = json.loads(request.body)
                self.assertEqual(payload["tag_name"], "v1.0.0")
                self.assertEqual(payload["body"], "text")
                self.assertEqual(payload["draft"], False)
                self.assertEqual(payload["prerelease"], False)
                self.assertEqual(
                    "Basic "
                    + base64.encodebytes(b"username:password").decode("ascii").strip(),
                    request.headers.get("Authorization"),
                )

                return 201, {}, json.dumps({})

            responses.add_callback(
                responses.POST,
                self.url,
                callback=request_callback,
                content_type="application/json",
            )

            with mock.patch.dict(os.environ, {"NETRC": netrc_file.name}):
                status = Gitea.post_release_changelog(
                    "gitea", "tea", "1.0.0", "text", False
                )
                self.assertTrue(status)

    @responses.activate
    def test_should_return_false_status_if_it_failed(self):
        responses.add(
            responses.POST,
            self.url,
            status=400,
            body="{}",
            content_type="application/json",
        )
        responses.add(
            responses.GET,
            self.get_url,
            status=200,
            body='{"id": 1}',
            content_type="application/json",
        )
        responses.add(
            responses.POST,
            self.edit_url,
            status=400,
            body="{}",
            content_type="application/json",
        )
        self.assertFalse(
            Gitea.post_release_changelog("gitea", "tea", "1.0.0", "text", False)
        )

    @responses.activate
    @mock.patch("semantic_release.hvcs.Gitea.token", return_value="super-token")
    def test_should_upload_asset(self, mock_token):
        # Create temporary file to upload
        dummy_file_path = os.path.join(temp_dir, "testupload.md")
        os.makedirs(os.path.dirname(dummy_file_path), exist_ok=True)
        dummy_content = "# Test File\n\n*Dummy asset for testing uploads.*"
        with open(dummy_file_path, "w") as dummy_file:
            dummy_file.write(dummy_content)

        def request_callback(request):
            self.assertTrue(dummy_content in request.body.decode())
            self.assertEqual(request.url, self.asset_url_params)
            self.assertTrue("multipart/form-data" in request.headers["Content-Type"])
            self.assertEqual("token super-token", request.headers.get("Authorization"))

            return 201, {}, json.dumps({})

        responses.add_callback(
            responses.POST, self.asset_url, callback=request_callback
        )
        status = Gitea.upload_asset("gitea", "tea", 1, dummy_file_path, "Dummy file")
        self.assertTrue(status)

        # Remove test file
        os.remove(dummy_file_path)

    @responses.activate
    @mock.patch("semantic_release.hvcs.Gitea.token", return_value="super-token")
    def test_should_upload_asset_with_no_extension(self, mock_token):
        # Create temporary file to upload
        dummy_file_path = os.path.join(temp_dir, "testupload-no-extension")
        os.makedirs(os.path.dirname(dummy_file_path), exist_ok=True)
        dummy_content = (
            "# Test File with no extension\n\n*Dummy asset for testing uploads.*"
        )
        with open(dummy_file_path, "w") as dummy_file:
            dummy_file.write(dummy_content)

        def request_callback(request):
            self.assertTrue(dummy_content in request.body.decode())
            self.assertEqual(request.url, self.asset_no_extension_url_params)
            self.assertTrue("multipart/form-data" in request.headers["Content-Type"])
            self.assertEqual("token super-token", request.headers["Authorization"])

            return 201, {}, json.dumps({})

        responses.add_callback(
            responses.POST, self.asset_url, callback=request_callback
        )
        status = Gitea.upload_asset(
            "gitea", "tea", 1, dummy_file_path, "Dummy file no extension"
        )
        self.assertTrue(status)

        # Remove test file
        os.remove(dummy_file_path)

    @responses.activate
    @mock.patch("semantic_release.hvcs.Gitea.token", return_value="super-token")
    def test_should_upload_dists(self, mock_token):
        # Create temporary file to upload
        dummy_file_path = os.path.join(temp_dir, "dist", "testupload.md")
        os.makedirs(os.path.dirname(dummy_file_path), exist_ok=True)
        dummy_content = "# Test File\n\n*Dummy asset for testing uploads.*"
        with open(dummy_file_path, "w") as dummy_file:
            dummy_file.write(dummy_content)

        def request_callback(request):
            self.assertTrue(dummy_content in request.body.decode())
            self.assertEqual(request.url, self.dist_asset_url_params)
            self.assertTrue("multipart/form-data" in request.headers["Content-Type"])
            self.assertEqual("token super-token", request.headers.get("Authorization"))

            return 201, {}, json.dumps({})

        responses.add(
            responses.GET,
            self.get_url,
            status=200,
            body='{"id": 1}',
            content_type="application/json",
        )
        responses.add_callback(
            responses.POST, self.asset_url, callback=request_callback
        )
        status = Gitea.upload_dists(
            "gitea", "tea", "1.0.0", os.path.dirname(dummy_file_path)
        )
        self.assertTrue(status)

        # Remove test file
        os.remove(dummy_file_path)


class GitlabReleaseTests(TestCase):
    @mock_gitlab()
    def test_should_return_true_if_success(self, mock_auth, mock_project):
        self.assertTrue(
            post_changelog("owner", "repo", "my_good_tag", "changelog", False)
        )

    @mock_gitlab()
    def test_should_return_false_if_bad_tag(self, mock_auth, mock_project):
        self.assertFalse(
            post_changelog("owner", "repo", "my_bad_tag", "changelog", False)
        )

    @mock_gitlab()
    def test_should_return_true_for_locked_tags(self, mock_auth, mock_project):
        self.assertTrue(
            post_changelog("owner", "repo", "my_locked_tag", "changelog", False)
        )


def test_gitea_token():
    with mock.patch("os.environ", {"GITEA_TOKEN": "token"}):
        assert Gitea.token() == "token"


def test_github_token():
    with mock.patch("os.environ", {"GH_TOKEN": "token"}):
        assert Github.token() == "token"
