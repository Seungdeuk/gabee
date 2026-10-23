-- 공용 DB 서버(PostgreSQL 16)에서 관리자(슈퍼유저)가 단계별로 실행하는 권한 정리. 자동 배포는 이 파일을 실행하지 않는다.
-- 이 PR 에서도 실행하지 않았다. 아래 STEP 1(읽기 전용)을 먼저 돌려 결과를 보고, STEP 2 의 방법 중 하나만 고른다.
-- 사용: psql -U postgres -d postgres -f db-hardening.sql   (비밀번호는 프롬프트로)
--
-- 왜 조심해야 하나
--   PostgreSQL 은 새 DB 에 PUBLIC(모든 롤)의 CONNECT 를 기본으로 준다. 그래서 gabee_app/gabee_migrator 가 MVP DB 에 접속하는 것도
--   보통 "PUBLIC 권한" 때문이다. `REVOKE CONNECT ... FROM gabee_app` 은 PUBLIC 몫을 못 막아 효과가 없고,
--   `REVOKE CONNECT ... FROM PUBLIC` 은 MVP 앱이 PUBLIC 권한으로 접속하고 있었다면 MVP 를 끊어 버린다.
--   따라서 (A) pg_hba.conf 거부 규칙(권한 변경 없음, 가장 안전) 또는 (B) 현재 접속하는 MVP 롤을 모두 확인해 명시 GRANT 한 뒤에만 PUBLIC 회수.

-- ============ STEP 1. 읽기 전용 점검 (아무것도 바꾸지 않는다) ============
\echo '--- DB 별 접속 권한(ACL, NULL 이면 기본값 = PUBLIC 이 CONNECT 가능) ---'
SELECT datname, datacl FROM pg_database WHERE NOT datistemplate ORDER BY 1;

\echo '--- 롤 속성 ---'
SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolcanlogin, rolconnlimit FROM pg_roles WHERE rolcanlogin ORDER BY 1;

\echo '--- 지금 DB 별로 접속 중인 롤 (MVP 가 어떤 롤을 쓰는지 확인 — 며칠에 걸쳐 여러 번 확인 권장) ---'
SELECT datname, usename, count(*) AS conns, max(backend_start) AS newest FROM pg_stat_activity WHERE datname IS NOT NULL GROUP BY 1, 2 ORDER BY 1, 2;

\echo '--- 각 롤이 각 DB 에 접속 가능한가 ---'
SELECT d.datname, r.rolname, has_database_privilege(r.rolname, d.datname, 'CONNECT') AS can_connect
FROM pg_database d CROSS JOIN pg_roles r WHERE NOT d.datistemplate AND r.rolcanlogin ORDER BY 1, 2;

\echo '--- pg_hba.conf 규칙(슈퍼유저만 조회 가능, PostgreSQL 15+) ---'
SELECT line_number, type, database, user_name, address, auth_method FROM pg_hba_file_rules ORDER BY line_number;

-- ============ STEP 2-A. (권장) pg_hba.conf 로 막기: DB 권한을 바꾸지 않는다 ============
-- 파일의 다른 gabee 규칙보다 *위에* 아래 두 줄을 추가하고 `SELECT pg_reload_conf();` (재시작 불필요, 되돌리려면 줄 삭제 후 reload).
--   host  family-secretary  gabee_app,gabee_migrator  all  reject
--   host  gabee             gabee_migrator            <개발 PC 대역 제외한 허용 대역>  scram-sha-256   # 배포 계정은 DB PC 에서만
-- (Docker 로 운영한다면 hba 파일은 컨테이너 데이터 폴더 안에 있다. 편집 전에 백업하고, 도커 안/밖 접속 출발지 주소가 다름에 주의)

-- ============ STEP 2-B. SQL 로 막기 (STEP 1 결과로 MVP 가 쓰는 롤을 전부 확인한 뒤에만) ============
-- 아래는 기본적으로 주석 처리돼 있다. <mvp_role> 을 STEP 1 에서 확인한 롤로 바꾸고, 한 줄씩 의도를 확인하며 실행한다.
--
-- BEGIN;
--   -- 1) MVP 가 지금 쓰는 모든 롤(앱, 백업, 모니터링, 관리자)에 명시적으로 CONNECT 를 준다 → 이후 PUBLIC 회수의 영향이 없다
--   GRANT CONNECT ON DATABASE "family-secretary" TO <mvp_role>;      -- 롤마다 반복
--   -- 2) 그 다음에야 PUBLIC 회수
--   REVOKE CONNECT ON DATABASE "family-secretary" FROM PUBLIC;
--   -- 3) 검증: MVP 롤은 true, gabee 롤은 false 여야 한다. 아니면 ROLLBACK
--   SELECT r, has_database_privilege(r, 'family-secretary', 'CONNECT') FROM unnest(ARRAY['<mvp_role>','gabee_app','gabee_migrator']) r;
-- COMMIT;   -- 이상하면 ROLLBACK;
--
-- 되돌리기(문제가 생기면 즉시):  GRANT CONNECT ON DATABASE "family-secretary" TO PUBLIC;
--
-- gabee DB 도 같은 방식으로 PUBLIC 회수 후 필요한 롤에만 부여할 수 있으나, 이미 접속 중인 다른 도구(백업 등)가 있는지 STEP 1 로 확인한다:
--   GRANT CONNECT ON DATABASE gabee TO gabee_app, gabee_migrator;  REVOKE CONNECT ON DATABASE gabee FROM PUBLIC;

-- ============ STEP 3. 배포/앱 계정 최소 권한 (MVP 와 무관, 위험 낮음) ============
-- 롤이 슈퍼유저가 아니고 DB·롤 생성 권한이 없는지는 STEP 1 의 롤 속성으로 확인했다. 필요할 때만:
-- ALTER ROLE gabee_migrator NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
-- ALTER ROLE gabee_migrator CONNECTION LIMIT 4;     -- 배포 1건 = 접속 2~3개
-- ALTER ROLE gabee_migrator SET idle_in_transaction_session_timeout = '5min';
-- ALTER ROLE gabee_app NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
--
-- 새 테이블에 gabee_app 이 CRUD 만 갖게 하는 기본 권한(배포 후 점검도 확인한다). gabee DB 안에서:
--   \connect gabee
--   ALTER DEFAULT PRIVILEGES FOR ROLE gabee_migrator IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO gabee_app;
--   ALTER DEFAULT PRIVILEGES FOR ROLE gabee_migrator IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO gabee_app;
