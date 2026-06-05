CREATE TABLE portali_bandi (
    id INT AUTO_INCREMENT PRIMARY KEY,
    numero INT COMMENT 'Corrisponde al N° progressivo',
    cliente VARCHAR(255) NOT NULL,
    gruppo VARCHAR(100),
    link_http VARCHAR(2083) COMMENT 'URL del portale',
    user VARCHAR(150),
    psw VARCHAR(255) COMMENT 'Password (valuta di cifrarla se sensibile)',
    note TEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;