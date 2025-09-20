-- Create database
CREATE DATABASE IF NOT EXISTS login_id;
USE login_id;

-- ======================
-- Tables
-- ======================

-- Authentication table
CREATE TABLE IF NOT EXISTS user (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Application users
CREATE TABLE IF NOT EXISTS users (
    user_id INT AUTO_INCREMENT PRIMARY KEY,  
    full_name VARCHAR(100) NOT NULL,        
    email VARCHAR(150) NOT NULL UNIQUE,      
    username VARCHAR(50) NOT NULL UNIQUE,    
    password_hash VARCHAR(255) NOT NULL,    
    phone VARCHAR(20),                        
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    status ENUM('active', 'inactive') DEFAULT 'active'
);

-- Submissions
CREATE TABLE IF NOT EXISTS submission (
  id            BIGINT PRIMARY KEY AUTO_INCREMENT,
  user_id       BIGINT NULL,
  input_type    ENUM('text','image','audio') NOT NULL,
  input_text    LONGTEXT NULL,
  media_url     VARCHAR(1024) NULL,  
  language      VARCHAR(10) NULL,
  content_hash  CHAR(64) NOT NULL,    
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_content (content_hash),
  FULLTEXT KEY ft_input (input_text)  
) ENGINE=InnoDB;

-- Results
CREATE TABLE IF NOT EXISTS result (
  id              BIGINT PRIMARY KEY AUTO_INCREMENT,
  submission_id   BIGINT NOT NULL,
  source          ENUM('google_fact_check','gemini','own_model') NOT NULL,
  verdict         ENUM('true','false','unknown') NOT NULL DEFAULT 'unknown',
  confidence      DECIMAL(5,4) NULL,        
  explanation     MEDIUMTEXT NULL,
  citations       JSON NULL,
  raw             JSON NULL,                  
  model_version   VARCHAR(50) NULL,          
  latency_ms      INT NULL,
  can_show_source BOOLEAN NOT NULL DEFAULT TRUE,
  created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_src_per_submission (submission_id, source),
  INDEX idx_submission (submission_id),
  CONSTRAINT fk_result_submission
    FOREIGN KEY (submission_id) REFERENCES submission(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Final decision
CREATE TABLE IF NOT EXISTS final_decision (
  id bigint primary key auto_increment,
  submission_id     BIGINT ,
  final_source      ENUM('google_fact_check','gemini','own_model') NOT NULL,
  final_verdict     ENUM('true','false','unknown') NOT NULL,
  final_confidence  DECIMAL(5,4) NULL,
  final_explanation MEDIUMTEXT NULL,
  decided_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_final_submission
    FOREIGN KEY (submission_id) REFERENCES submission(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- Feedback
CREATE TABLE IF NOT EXISTS feedback (
  id             BIGINT PRIMARY KEY AUTO_INCREMENT,
  submission_id  BIGINT NOT NULL,
  label          ENUM('true','false') NOT NULL,    
  label_source   ENUM('human','google','other') NOT NULL DEFAULT 'human',
  notes          TEXT NULL,
  created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_feedback_submission
    FOREIGN KEY (submission_id) REFERENCES submission(id) ON DELETE CASCADE
) ENGINE=InnoDB;

-- ======================
-- Procedure + Triggers
-- ======================
DELIMITER $$

CREATE PROCEDURE compute_final(IN p_submission_id BIGINT)
BEGIN
   DECLARE v_src VARCHAR(100);
   DECLARE v_verdict VARCHAR(20);
   DECLARE v_conf DECIMAL(5,4);
   DECLARE v_expl MEDIUMTEXT;

   -- Prefer Google Fact Check
   SELECT 'google_fact_check', verdict, IFNULL(confidence,1.0), explanation
      INTO v_src, v_verdict, v_conf, v_expl
   FROM result
   WHERE submission_id=p_submission_id
     AND source='google_fact_check'
   ORDER BY confidence DESC
   LIMIT 1;

   -- If no Google result, check own_model
   IF v_src IS NULL THEN
      SELECT 'own_model', verdict, IFNULL(confidence,0), explanation
        INTO v_src, v_verdict, v_conf, v_expl
      FROM result
      WHERE submission_id=p_submission_id
        AND source='own_model'
      ORDER BY confidence DESC
      LIMIT 1;

      -- If confidence too low, fall back to Gemini
      IF v_src IS NULL OR v_conf < 0.60 THEN
         SELECT 'gemini', verdict, IFNULL(confidence,NULL), explanation
           INTO v_src, v_verdict, v_conf, v_expl
         FROM result
         WHERE submission_id=p_submission_id
           AND source='gemini'
         ORDER BY confidence DESC
         LIMIT 1;
      END IF;
   END IF;

   -- Default to unknown
   IF v_src IS NULL THEN
      SET v_src='gemini';
      SET v_verdict='unknown';
      SET v_conf=NULL;
      SET v_expl=NULL;
   END IF;

   -- Insert or update final_decision
   INSERT INTO final_decision
   (submission_id, final_source, final_verdict, final_confidence, final_explanation)
   VALUES (p_submission_id, v_src, v_verdict, v_conf, v_expl)
   ON DUPLICATE KEY UPDATE
     final_source = VALUES(final_source),
     final_verdict = VALUES(final_verdict),
     final_confidence = VALUES(final_confidence),
     final_explanation = VALUES(final_explanation),
     decided_at = CURRENT_TIMESTAMP;
END$$

-- Triggers
CREATE TRIGGER trg_result_ai
AFTER INSERT ON result
FOR EACH ROW BEGIN
  CALL compute_final(NEW.submission_id);
END$$

CREATE TRIGGER trg_result_au
AFTER UPDATE ON result
FOR EACH ROW BEGIN
  CALL compute_final(NEW.submission_id);
END$$
DELIMITER ;

-- ======================
-- Views
-- ======================
CREATE OR REPLACE VIEW v_submission_summary AS
SELECT
 s.id,
 s.input_type,
 s.input_text,
 s.media_url,
 s.created_at,
 f.final_source,
 f.final_verdict,
 f.final_confidence,
 f.final_explanation
FROM submission s
LEFT JOIN final_decision f ON f.submission_id=s.id;

CREATE OR REPLACE VIEW v_training_gold AS
SELECT s.id AS submission_id,
       s.input_text,
       fb.label AS gold_label,
       fb.created_at AS labeled_at
FROM submission s
JOIN (
   SELECT submission_id, MAX(created_at) AS latest
   FROM feedback
   GROUP BY submission_id
) fbmax ON fbmax.submission_id = s.id
JOIN feedback fb ON fb.submission_id = fbmax.submission_id 
                AND fb.created_at = fbmax.latest;

-- ======================
-- Example Data
-- ======================
INSERT INTO submission (user_id, input_type, input_text, content_hash, language)
VALUES (130, 'text', 'The quick red ', SHA2('The quick red ', 256), 'en');
SET @sid = LAST_INSERT_ID();

INSERT INTO result (submission_id, source, verdict, confidence, explanation, citations, raw)
VALUES
(@sid, 'google_fact_check', 'false', 0.95,
 'Multiple reputable sources confirm the quick brown fox.',
 JSON_ARRAY('https://example.com/source2','https://example.com/source3'),
 JSON_OBJECT('provider','google'));

INSERT INTO submission (user_id, input_type, input_text, content_hash, language)
VALUES (234, 'text', 'Water boils at 100°C at sea level.', SHA2('Water boils at 100°C at sea level.', 256), 'en');
SET @sid2 = LAST_INSERT_ID();

INSERT INTO result (submission_id, source, verdict, confidence, explanation)
VALUES
(@sid2, 'own_model', 'true', 0.87, 'High confidence from domain facts.'),
(@sid2, 'gemini', 'true', 0.72, 'Based on physics reference.');

INSERT INTO submission (user_id, input_type, input_text, content_hash, language)
VALUES (345, 'text', 'The moon is made of cheese.', SHA2('The moon is made of cheese.', 256), 'en');
SET @sid3 = LAST_INSERT_ID();

INSERT INTO result (submission_id, source, verdict, confidence, explanation)
VALUES
(@sid3, 'own_model', 'false', 0.41, 'Weak signal.'),
(@sid3, 'gemini',    'false', 0.93, 'Astronomy sources refute this.');

-- ======================
-- Indexes
-- ======================
CREATE INDEX idx_submission_user ON submission(user_id);
CREATE INDEX indx_result_submission ON result(submission_id);

-- ✅ Removed app_user creation since you are using root@localhost
