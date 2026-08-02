def test_fake_response_matches_sdk_shape(fake_response):
    response = fake_response({"items": [{"id": "site-1"}]})

    assert response.cgx_status is True
    assert response.cgx_content == {"items": [{"id": "site-1"}]}
    assert response.status_code == 200