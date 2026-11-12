"""실제 모델 호출을 허용하는 스위치. 기본은 꺼짐이고, 켜는 것은 E7(첫 실제 호출)에서 비용 추정·승인·안전장치를 다시 점검한 뒤에 한다.

CLI(`cli.make_plan`·`cli._execute`)와 실행기(`runner._check_options`)가 호출할 때마다 읽는다. 시험은 `monkeypatch` 로만 바꾼다.
"""

REAL_ENABLED = False
