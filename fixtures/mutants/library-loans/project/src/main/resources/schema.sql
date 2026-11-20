CREATE TABLE title (
    title_id BIGINT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    author VARCHAR(120) NOT NULL,
    isbn VARCHAR(20) NOT NULL
);

CREATE TABLE loan (
    loan_id BIGINT PRIMARY KEY,
    member_login VARCHAR(48) NOT NULL,
    title_id BIGINT NOT NULL REFERENCES title(title_id),
    due_date DATE NOT NULL,
    home_address VARCHAR(200) NOT NULL
);
